import os
import json
from flask import Flask, request, jsonify
import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import threading
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# Constants from Docker environment variables
BASE_URL = os.environ.get('BASE_URL', 'https://platform.plutonium.pw/serverkeys/')
COOKIE = os.environ.get('COOKIE', '')

# Constants
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Sec-GPC": "1",
    "Connection": "keep-alive",
    "Alt-Used": "platform.plutonium.pw",
}

# File path for storing keys in Docker volume
KEY_STORAGE_FILE = '/data/key_storage.json'

# Load existing keys from file
def load_key_storage():
    if os.path.exists(KEY_STORAGE_FILE):
        with open(KEY_STORAGE_FILE, 'r') as f:
            return json.load(f)
    return {}

# Save keys to file
def save_key_storage():
    with open(KEY_STORAGE_FILE, 'w') as f:
        json.dump(key_storage, f)

key_storage = load_key_storage()
key_storage_lock = threading.Lock()

scheduler = BackgroundScheduler()
scheduler.start()

def get_headers(is_post=False):
    headers = COMMON_HEADERS.copy()
    headers["Cookie"] = COOKIE
    if is_post:
        headers.update({
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Referer": BASE_URL,
            "Origin": "https://platform.plutonium.pw",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Content-Type": "application/json",
            "Sec-Fetch-Site": "same-origin",
            "Sec-CH-UA": '"Chromium";v="127", "Not)A;Brand";v="99"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Priority": "u=1, i",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache"
        })
    else:
        headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8",
            "Accept-Encoding": "identity",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Priority": "u=0, i",
            "TE": "trailers"
        })
    return headers

def delete_key(key):
    delete_url = f"{BASE_URL}{key}"
    headers = get_headers(is_post=True)
    headers.update({
        "Accept": "*/*",
        "Referer": delete_url,
        "Sec-Fetch-Mode": "cors",
    })
    response = requests.delete(delete_url, headers=headers)
    if response.status_code == 204:
        print(f"Key {key} deleted successfully.")
    else:
        print(f"Failed to delete key {key}. Status code: {response.status_code}")

def schedule_key_deletion(key):
    scheduler.add_job(delete_key, 'date', run_date=datetime.now() + timedelta(hours=48), args=[key])

@app.route('/plutonium-key-generator', methods=['POST'])
def generate_key():
    data = request.json
    hostname = data.get('server_name')
    game = data.get('mode')
    client_ip = request.remote_addr

    with key_storage_lock:
        # Check existing keys
        for stored_key, info in key_storage.items():
            if info['hostname'] == hostname and info['game'] == game:
                if datetime.fromisoformat(info['expiration']) > datetime.now():
                    return jsonify({"key": stored_key})
            if info.get('client_ip') == client_ip:
                return jsonify({"error": "This IP has already generated a key"}), 403

    # If no valid key found, generate a new one
    payload = {"hostname": hostname, "game": game}
    post_response = requests.post(BASE_URL, headers=get_headers(is_post=True), json=payload)
    
    if post_response.status_code != 204:
        return jsonify({"error": "Failed to create the key"}), post_response.status_code

    time.sleep(1)

    get_response = requests.get(BASE_URL, headers=get_headers())
    get_response.encoding = 'utf-8'
    
    if get_response.status_code != 200:
        return jsonify({"error": "Unable to retrieve the key"}), get_response.status_code

    soup = BeautifulSoup(get_response.text, 'html.parser')
    items = soup.find_all('div', class_='item')
    
    for item in items:
        item_hostname = item.find('div', class_='hostname').text.strip()
        item_game = item.find('div', class_='game').text.strip()
        if item_hostname == hostname and item_game == game:
            key = item.find('div', class_='key').text.strip()
            # Store the key with expiration time and client IP
            key_storage[key] = {
                'hostname': hostname,
                'game': game,
                'expiration': (datetime.now() + timedelta(hours=48)).isoformat(),
                'client_ip': client_ip
            }
            save_key_storage()  # Save updated key storage to file
            # Schedule key deletion after 48 hours
            schedule_key_deletion(key)
            return jsonify({"key": key})
    
    return jsonify({"error": "Key not found"}), 404

if __name__ == '__main__':
    app.run()