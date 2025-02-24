import os
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from urllib.parse import urlparse, urlunparse, urljoin
from datetime import datetime, timedelta, timezone
import unicodedata
from typing import List
import gzip
import io

import requests
from dotenv import load_dotenv
from collections import namedtuple

# Load configuration
load_dotenv()


# methods
def fetch_w3u_playlist(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        w3u_content = response.text

        # W3U is like JSON inside a text file, need to parse it as JSON
        try:
            # Find the JSON part within the W3U file (assuming it starts with '{' and ends with '}')
            start_index = w3u_content.find('{')
            end_index = w3u_content.rfind('}') + 1  # Include the closing '}'
            if start_index != -1 and end_index > start_index:
                json_string = w3u_content[start_index:end_index]
                playlist_data = json.loads(json_string)
            else:
                print("Error: Could not find valid JSON content in W3U file.")
                return None

            channels_data = []
            groups = playlist_data.get("groups", [])
            for group in groups:
                group_name = group.get("name", "No Group")
                stations = group.get("stations", [])
                for station in stations:
                    channel_info = {
                        "name": station.get("name", "No Name"),
                        "tvg_id": station.get("epgId", station.get("name", "no_epg_id")).replace(" ", "-").lower(),  # Fallback and normalize
                        "logo_url": station.get("image", ""),
                        "group_title": group_name,
                        "stream_url": station.get("url", ""),
                        "qualities": []  # Initialize qualities list
                    }
                    channels_data.append(channel_info)
            return channels_data

        except json.JSONDecodeError as e:
            print(f"JSONDecodeError parsing W3U content: {e}")
            print("Problematic content:", w3u_content)  # Print content for debugging
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching W3U playlist from {url}: {e}")
        return None

def fetch_m3u8_qualities(master_url):
    qualities = []
    seen_urls = set()  # To track unique URLs
    try:
        response = requests.get(master_url, timeout=10)
        response.raise_for_status()
        m3u8_content = response.text
        base_url = urlparse(master_url).geturl()  # Get base URL for resolving relative URLs

        lines = m3u8_content.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('#EXT-X-STREAM-INF'):
                attributes_str = line[len('#EXT-X-STREAM-INF:'):]
                attributes = {}
                for attribute in attributes_str.split(','):
                    if '=' in attribute:
                        key, value = attribute.split('=', 1)
                        attributes[key] = value.strip('"')
                i += 1
                if i < len(lines):
                    url_line = lines[i]
                    if url_line and not url_line.startswith('#'):
                        absolute_url = urljoin(base_url, url_line)  # Resolve relative URLs
                        if absolute_url not in seen_urls:  # Check if URL is already seen
                            quality_info = {
                                "url": absolute_url,
                                "attributes": attributes
                            }
                            qualities.append(quality_info)
                            seen_urls.add(absolute_url)  # Add URL to seen URLs set
            i += 1
    except requests.exceptions.RequestException as e:
        print(f"Error fetching M3U8 playlist from {master_url}: {e}")
    return qualities


def fetch_epg_xml_data(url):
    try:
        response = requests.get(url, stream=True, timeout=10)  # stream=True for large gzip files
        response.raise_for_status()

        with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as f:
            xml_content = f.read()

        root = ET.fromstring(xml_content)
        epg_data = {}
        current_time_utc = datetime.now(timezone.utc)  # Get current time in UTC

        for channel_element in root.findall('channel'):
            channel_id = channel_element.get('id')
            epg_data[channel_id] = []  # Initialize list for each channel

        for program_element in root.findall('programme'):
            channel_epg_id = program_element.get('channel')
            start_time_str = program_element.get('start')
            stop_time_str = program_element.get('stop')
            title_element = program_element.find('title')
            title_text = title_element.text if title_element is not None else "No Title"
            desc_element = program_element.find('desc')
            desc_text = desc_element.text if desc_element is not None else "No Description"
            icon_element = program_element.find('icon')
            icon_src = icon_element.get('src') if icon_element is not None else None

            try:
                # Parse time strings to datetime objects, assuming they include timezone info
                start_time = datetime.strptime(start_time_str, "%Y%m%d%H%M%S %z")
                stop_time = datetime.strptime(stop_time_str, "%Y%m%d%H%M%S %z")

                if stop_time > current_time_utc:  # Filter out past programs
                    epg_data[channel_epg_id].append({
                        "start_time": start_time_str,
                        "stop_time": stop_time_str,
                        "title": title_text,
                        "description": desc_text,
                        "icon": icon_src
                    })
            except ValueError:
                print(f"Error parsing time for program '{title_text}'. Skipping program.")


        return epg_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching EPG XML from {url}: {e}")
        return {}  # Return empty dict in case of error
    except ET.ParseError as e:
        print(f"Error parsing EPG XML content: {e}")
        return {}
    except gzip.BadGzipFile as e:
        print(f"Error decompressing gzip EPG file: {e}")
        return {}


def create_m3u_playlist(channels_data):
    epg_url_m3u_header = "https://github.com/joaquinito2070/rakuten-m3u/raw/refs/heads/main/rakuten_epg.xml"
    playlist = f"#EXTM3U url-tvg=\"{epg_url_m3u_header}\"\n"
    seen_urls = set()

    for channel_info in channels_data:
        channel_name = channel_info['name']
        stream_url = channel_info['stream_url']  # Use master URL here
        tvg_id = channel_info['tvg_id']
        logo_url = channel_info['logo_url']
        group_title = channel_info['group_title']

        if stream_url and stream_url not in seen_urls and stream_url != "# no_url":
            playlist += f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo_url}" group-title="{group_title}",{channel_name}\n{stream_url}\n'
            seen_urls.add(stream_url)
    return playlist

def convert_to_xmltv_format(xmltv_time):
    return xmltv_time  # Already in XMLTV format from fetched EPG

def create_epg_xml(channels_data, epg_data_map):
    root = ET.Element("tv")

    for channel_info in channels_data:
        station = channel_info
        channel = ET.SubElement(root, "channel", id=str(station.get("tvg_id")))
        display_name = ET.SubElement(channel, "display-name")
        display_name.text = station.get("name", "Unknown Title")

        icon = ET.SubElement(channel, "icon", src=station.get("logo_url"))

        channel_epg_id = station.get("tvg_id")
        if channel_epg_id in epg_data_map:
            for program in epg_data_map[channel_epg_id]:
                programme = ET.SubElement(root, "programme", channel=str(station.get("tvg_id")))

                start_time = program.get("start_time", "")
                stop_time = program.get("stop_time", "")

                programme.set("start", start_time)
                programme.set("stop", stop_time)

                title = ET.SubElement(programme, "title")
                title.text = program.get("title", "")

                if program.get("description"):
                    desc = ET.SubElement(programme, "desc")
                    desc.text = program.get("description", "")

                program_icon_src = program.get("icon")  # Get program icon src from epg_data_map
                if program_icon_src:  # Add icon only if src exists
                    icon_element = ET.SubElement(programme, "icon", src=program_icon_src)


    tree = ET.ElementTree(root)
    return tree

def save_file(content, filename):
    script_directory = os.path.dirname(os.path.abspath(__file__))
    parent_directory = os.path.dirname(script_directory)
    file_path = os.path.join(parent_directory, filename)
    os.makedirs(os.path.dirname(file_path), exist_ok=True) # Ensure directory exists

    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)
    print(f"File saved: {file_path}")

def save_epg_to_file(tree, filename):
    script_directory = os.path.dirname(os.path.abspath(__file__))
    parent_directory = os.path.dirname(script_directory)
    file_path = os.path.join(parent_directory, filename)
    os.makedirs(os.path.dirname(file_path), exist_ok=True) # Ensure directory exists

    tree.write(file_path, encoding='utf-8', xml_declaration=True)
    print(f"EPG XML file saved: {file_path}")

def save_json_output(data, filename):
    script_directory = os.path.dirname(os.path.abspath(__file__))
    parent_directory = os.path.dirname(script_directory)
    file_path = os.path.join(parent_directory, filename)
    os.makedirs(os.path.dirname(file_path), exist_ok=True) # Ensure directory exists

    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
    print(f"JSON file saved: {file_path}")

def create_channel_master_m3u8(qualities):
    playlist_content = "#EXTM3U\n"
    for quality in qualities:
        attributes_str = ','.join([f'{k}="{v}"' for k, v in quality['attributes'].items()])
        playlist_content += f'#EXT-X-STREAM-INF:{attributes_str}\n{quality["url"]}\n'
    return playlist_content

def create_channel_json_data(channel_info, backup_master_url):
    channel_json = {
        "name": channel_info['name'],
        "tvg_id": channel_info['tvg_id'],
        "logo_url": channel_info['logo_url'],
        "group_title": channel_info['group_title'],
        "original_master_url": channel_info['stream_url'],
        "backup_master_url": backup_master_url,
        "qualities": channel_info['qualities'],
        "epg": channel_info['epg']
    }
    return channel_json


def main():
    w3u_url = "https://github.com/HelmerLuzo/RakutenTV_HL/raw/refs/heads/main/tv/w3u/RakutenTV_tv.w3u"
    epg_url = "https://helmerluzo.github.io/RakutenTV_HL/epg/RakutenTV.xml.gz"
    output_filename_m3u = "rakuten_playlist.m3u"
    output_filename_epg = "rakuten_epg.xml"
    output_filename_json = "rakuten_channels.json"
    github_base_url = "https://raw.githubusercontent.com/joaquinito2070/rakuten-m3u/refs/heads/main/"


    print(f"Fetching W3U playlist from: {w3u_url}")
    channels_data = fetch_w3u_playlist(w3u_url)
    if not channels_data:
        print("Failed to fetch W3U playlist. Exiting.")
        return

    print(f"Found {len(channels_data)} channels in W3U playlist.")

    for channel_info in channels_data:
        master_url = channel_info['stream_url']
        tvg_id = channel_info['tvg_id']
        if master_url and master_url != "# no_url":
            print(f"Fetching qualities for channel: {channel_info['name']} from {master_url}")
            channel_info['qualities'] = fetch_m3u8_qualities(master_url)

            # Generate master.m3u8 for each channel
            channel_master_m3u8_content = create_channel_master_m3u8(channel_info['qualities'])
            master_m3u8_filename = f"master/{tvg_id}/master.m3u8"
            save_file(channel_master_m3u8_content, master_m3u8_filename)

            # Generate channel JSON
            backup_master_url = f"{github_base_url}master/{tvg_id}/master.m3u8"
            channel_json_data = create_channel_json_data(channel_info, backup_master_url)
            channel_json_filename = f"json/{tvg_id}.json"
            save_json_output(channel_json_data, channel_json_filename)


    print(f"Fetching EPG data from: {epg_url}")
    epg_data_map = fetch_epg_xml_data(epg_url)
    if not epg_data_map:
        print("Failed to fetch or parse EPG data. Continuing without EPG.")
        epg_data_map = {}  # Proceed without EPG if fetch fails

    # Integrate EPG data into channels_data for JSON output
    current_time_utc_main = datetime.now(timezone.utc)  # Get current time in UTC for main function

    for channel_info in channels_data:
        channel_epg_id = channel_info['tvg_id']
        channel_epg = epg_data_map.get(channel_epg_id, [])

        future_epg_programs = []  # List to hold future programs
        for program in channel_epg:
            try:
                stop_time = datetime.strptime(program['stop_time'], "%Y%m%d%H%M%S %z")
                if stop_time > current_time_utc_main:  # Filter programs in main function too for JSON
                    future_epg_programs.append(program)
            except ValueError:
                print(f"Error parsing time for program '{program.get('title', 'No Title')}' in main function. Skipping program for JSON.")

        channel_info['epg'] = future_epg_programs  # Assign filtered list back
        for program in channel_info['epg']:  # Ensure icon key is present in JSON output for future programs
            program['icon'] = program.get('icon')


    # Create M3U playlist and EPG files (original playlist with master urls)
    m3u_playlist = create_m3u_playlist(channels_data)
    epg_tree = create_epg_xml(channels_data, epg_data_map)  # create_epg_xml uses the full epg_data_map, filtered in fetch_epg_xml_data

    # Save files (original playlist files)
    save_file(m3u_playlist, output_filename_m3u)
    save_epg_to_file(epg_tree, output_filename_epg)
    save_json_output({"channels": channels_data}, output_filename_json)


if __name__ == "__main__":
    main()
