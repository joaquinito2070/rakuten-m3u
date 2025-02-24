import os
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timedelta # Import timedelta explicitly
import unicodedata
from typing import List

import requests
from dotenv import load_dotenv
from collections import namedtuple

# Channel definition
CHANNEL_FIELDS = [
    "id",
    "numerical_id",
    "title",
    "type",
    "channel_number",
    "category",
    "language_ids",
]

Channel = namedtuple("Channel", CHANNEL_FIELDS)

# Load configuration
load_dotenv()


class Api:
    api_scheme = "https"
    api_domain = "gizmo.rakuten.tv"
    api_base_path = "/v3"
    api_base_url = "{}://{}{}".format(
        api_scheme,
        api_domain,
        api_base_path
    )

    origin = "https://rakuten.tv"
    referer = "https://rakuten.tv/"
    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0"

    language = os.getenv('CLASSIFICATION', 'it')

    classification_id = {
        "al": 270,
        "at": 300,
        "ba": 245,
        "be": 308,
        "bg": 269,
        "ch": 319,
        "cz": 272,
        "de": 307,
        "dk": 283,
        "ee": 288,
        "es": 5,
        "fi": 284,
        "fr": 23,
        "gr": 279,
        "hr": 302,
        "ie": 41,
        "is": 287,
        "it": 36,
        "jp": 309,
        "lt": 290,
        "lu": 74,
        "me": 259,
        "mk": 275,
        "nl": 69,
        "no": 286,
        "pl": 277,
        "pt": 64,
        "ro": 268,
        "rs": 266,
        "se": 282,
        "sk": 273,
        "uk": 18,
    }


    @classmethod
    def get_live_channels(cls, language):
        path = "/live_channels"
        headers = {
            "Origin": cls.origin,
            "Referer": cls.referer,
            "User_Agent": cls.user_agent,
        }
        query = {
            "classification_id": cls.classification_id[language],
            "device_identifier": "web",
            "locale": language,
            "market_code": language,
            "page": 1,
            "per_page": 100,
        }

        response = requests.get(
            cls.api_base_url + path,
            headers=headers,
            params=query,
        )

        return response.json()


    @classmethod
    def get_live_channel_categories(cls, language):
        path = "/live_channel_categories"
        headers = {
            "Origin": cls.origin,
            "Referer": cls.referer,
            "User_Agent": cls.user_agent,
        }
        query = {
            "classification_id": cls.classification_id[language],
            "device_identifier": "web",
            "locale": language,
            "market_code": language
        }

        response = requests.get(
            cls.api_base_url + path,
            headers=headers,
            params=query,
        )

        return response.json()


    @classmethod
    def get_live_streaming(cls, channel: Channel, language, session: requests.Session = None):
        path = "/avod/streamings"
        headers = {
            "Origin": cls.origin,
            "Referer": cls.referer,
            "User_Agent": cls.user_agent,
        }
        query = {
            "classification_id": cls.classification_id[language],
            "device_identifier": "web",
            "device_stream_audio_quality": "2.0",
            "device_stream_hdr_type": "NONE",
            "device_stream_video_quality": "FHD",
            "disable_dash_legacy_packages": False,
            "locale": language,
            "market_code": language
        }

        data = {
            "audio_language": channel.language_ids[0],
            "audio_quality": "2.0",
            "classification_id": cls.classification_id[language],
            "content_id": channel.id,
            "content_type": "live_channels",
            "device_serial": "not implemented",
            "player": "web:HLS-NONE:NONE",
            "strict_video_quality": False,
            "subtitle_language": "MIS",
            "video_type": "stream"
        }

        if session:
            caller = session
        else:
            caller = requests

        response = caller.post(
            cls.api_base_url + path,
            headers=headers,
            params=query,
            json=data,
        )

        return response.json()


# methods
def map_channels_categories(api_response):
    categories = api_response.get("data", [])

    channels_categories_map = {}
    for category in categories:
        name = category.get("name", "no_category")
        channels = category.get("live_channels", [])

        for channel_id in channels:  # category contains channel ids only
            channels_categories_map[channel_id] = name

    return channels_categories_map


def map_channels_streams(channels: List[Channel], language):
    session = requests.Session()

    ch_stream_map = {}

    for channel in channels:
        stream_url = "# no_url"  # Default value
        stream_url_data = Api.get_live_streaming(channel, language, session)

        if stream_url_data is None:
            print(f"Error: get_live_streaming response is None for channel {channel.title} ({channel.id}), language {language}. Skipping stream URL fetch.")
            continue  # Skip to the next channel

        if 'errors' in stream_url_data: # Check for 'errors' key directly
            errors = stream_url_data.get('errors')
            print(f"Error: API returned errors for channel {channel.title} ({channel.id}), language {language}. Errors: {errors}. Skipping stream URL fetch.")
            continue # Skip to the next channel


        data = stream_url_data.get("data")
        if data is None:
            print(f"Error: 'data' key not found in get_live_streaming response for channel {channel.title} ({channel.id}), language {language}. Response: {stream_url_data}. Skipping stream URL fetch.")
            continue

        stream_infos = data.get("stream_infos")
        if not isinstance(stream_infos, list) or not stream_infos: # Check if stream_infos is a non-empty list
            print(f"Error: 'stream_infos' key not found or empty/not a list in 'data' for channel {channel.title} ({channel.id}), language {language}. Data: {data}. Skipping stream URL fetch.")
            continue

        stream_info = stream_infos[0]
        if stream_info is None:
            print(f"Error: First element of 'stream_infos' is None for channel {channel.title} ({channel.id}), language {language}. Stream_infos: {stream_infos}. Skipping stream URL fetch.")
            continue

        stream_url_candidate = stream_info.get("url")
        if stream_url_candidate:
            head, sep, tail = stream_url_candidate.partition('.m3u8')
            stream_url = head + sep
        else:
            print(f"Error: 'url' key not found in 'stream_info' for channel {channel.title} ({channel.id}), language {language}. Stream_info: {stream_info}. Skipping stream URL fetch.")
            continue


        ch_stream_map[channel.id] = stream_url

    return ch_stream_map


def get_channels(language) -> List[Channel]:
    live_channels_raw = Api.get_live_channels(language)
    categories_raw = Api.get_live_channel_categories(language)

    # make channels/category lookup map
    cc_map = map_channels_categories(categories_raw)

    # list of all live channels
    ch_list: List[Channel] = []

    channels = live_channels_raw.get("data", [])
    for channel in channels:

        ch_id = channel.get("id", "no_id")

        ch_languages = channel.get("labels", {}).get("languages", [])
        langs = []

        for lang in ch_languages:
            langs.append(lang.get("id"))

        ch = Channel(
            id = ch_id,
            numerical_id = int(channel.get("numerical_id", -1)),
            title = channel.get("title", "no_title"),
            type = channel.get("type", "no_type"),
            channel_number = int(channel.get("channel_number", -1)),
            category = cc_map.get(ch_id, "no_category"),
            language_ids = langs,
        )

        ch_list.append(ch)

    return ch_list

def clean_stream_url(url):
    parsed_url = urlparse(url)
    clean_url = urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path, '', '', ''))
    return clean_url

def normalize_text(text):
    normalized_text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    return normalized_text

def create_m3u_playlist(channels_data):
    playlist = "#EXTM3U\n"
    seen_urls = set()

    for channel_info in channels_data:
        channel_name = channel_info['name']
        stream_url = channel_info['stream_url']
        tvg_id = channel_info['tvg_id']
        logo_url = channel_info['logo_url']
        group_title = channel_info['group_title']

        if stream_url and stream_url not in seen_urls and stream_url != "# no_url": # Added check for "# no_url"
            playlist += f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo_url}" group-title="{group_title}",{channel_name}\n{stream_url}\n'
            seen_urls.add(stream_url)
    return playlist

def convert_to_xmltv_format(iso_time):
    """Convert ISO 8601 time to XMLTV format."""
    try:
        dt = datetime.strptime(iso_time, "%Y-%m-%dT%H:%M:%SZ")
        xmltv_time = dt.strftime("%Y%m%d%H%M%S +0000")
        return xmltv_time
    except ValueError:
        return iso_time

def create_epg_xml(channels_data): # channels_data now contains epg info
    root = ET.Element("tv")

    for channel_info in channels_data:
        station = channel_info
        channel = ET.SubElement(root, "channel", id=str(station.get("tvg_id"))) # use tvg_id as channel id in xmltv
        display_name = ET.SubElement(channel, "display-name")
        display_name.text = station.get("name", "Unknown Title") # use channel name

        icon = ET.SubElement(channel, "icon", src=station.get("logo_url")) # use logo url

        for program in station.get('epg', []): # use epg data from channel_info
            programme = ET.SubElement(root, "programme", channel=str(station.get("tvg_id"))) # use tvg_id

            start_time = program.get("start_time", "")
            stop_time = program.get("stop_time", "")

            programme.set("start", start_time)
            programme.set("stop", stop_time)

            title = ET.SubElement(programme, "title")
            title.text = program.get("title", "")

            if program.get("description"):
                desc = ET.SubElement(programme, "desc")
                desc.text = program.get("description", "")

    tree = ET.ElementTree(root)
    return tree

def save_file(content, filename):
    script_directory = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_directory, filename)

    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)
    print(f"File saved: {file_path}")

def save_epg_to_file(tree, filename):
    script_directory = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_directory, filename)

    tree.write(file_path, encoding='utf-8', xml_declaration=True)
    print(f"EPG XML file saved: {file_path}")

def save_json_output(data, filename):
    script_directory = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_directory, filename)

    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
    print(f"JSON file saved: {file_path}")

def fetch_epg_data_for_channels(channels: List[Channel], language):
    epg_data_for_channels = {}
    for channel in channels:
        epg_data_for_channels[channel.id] = [] # Initialize empty epg for each channel
        # EPG data is not directly available in Rakuten API as per provided example.
        # Placeholder EPG data creation or skip EPG if not possible.
        # For now, let's create placeholder EPG data
        epg_data_for_channels[channel.id].append({
            "start_time": convert_to_xmltv_format(datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")), # Use datetime.now() instead of utcnow()
            "stop_time": convert_to_xmltv_format((datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")), # Use datetime.now() and timedelta
            "title": "Placeholder Program",
            "description": "This is a placeholder EPG program. Real EPG data is not available from Rakuten API used in this script."
        })
    return epg_data_for_channels


def main():
    countries = list(Api.classification_id.keys()) # Use countries from Api class
    all_channels_data = []

    for country in countries:
        print(f"Fetching channels for country: {country}")
        channels: List[Channel] = get_channels(country)
        if not channels:
            print(f"No channels found for country {country}. Skipping...")
            continue

        print(f"Found {len(channels)} channels for country {country}")

        stream_url_map = map_channels_streams(channels, country)
        print(f"Fetched stream URLs for country {country}")

        epg_data_map = fetch_epg_data_for_channels(channels, country) # Fetch (placeholder) EPG data
        print(f"Fetched EPG data (placeholders) for country {country}")


        country_channels_data = []
        for channel in channels:
            stream_url = stream_url_map.get(channel.id, "")
            if not stream_url or stream_url == "# no_url":
                print(f"No stream URL found for channel {channel.title} ({channel.id}) due to API errors, skipping.") # More informative message
                continue

            channel_info = {
                "name": channel.title,
                "tvg_id": channel.id,
                "logo_url": "", # Rakuten API example doesn't provide logo URL in channel list
                "group_title": channel.category,
                "stream_url": stream_url,
                "epg": epg_data_map.get(channel.id, []) # Assign placeholder EPG data
            }
            all_channels_data.append(channel_info)
            country_channels_data.append(channel_info)


        # Create M3U playlist and EPG files
        m3u_playlist = create_m3u_playlist(country_channels_data)
        epg_tree = create_epg_xml(country_channels_data)

        # Save files with country code
        save_file(m3u_playlist, f"rakuten_playlist_{country.lower()}.m3u")
        save_epg_to_file(epg_tree, f"rakuten_epg_{country.lower()}.xml")


    # Save all channels data to a single JSON file after processing all countries
    save_json_output({"channels": all_channels_data}, "rakuten_channels_all.json")

if __name__ == "__main__":
    main()
