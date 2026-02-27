#!/usr/bin/env python3
"""
search.py — Utilize the Brave Search API
"""
import os
import requests
from dotenv import load_dotenv

# Load environment variables
def load_api_key():
    load_dotenv()
    return os.getenv('BRAVE_API_KEY')

# Initialize Brave API key
BRAVE_API_KEY = load_api_key()
def search(query):
    url = f'https://api.search.brave.com/res/v1/web/search?q={query}'
    headers = { 
    'Authorization': f'Bearer {BRAVE_API_KEY}',
    'x-subscription-token': os.getenv('BRAVE_SUBSCRIPTION_TOKEN') 
}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f'Error {response.status_code}: {response.text}')

if __name__ == '__main__':
    import sys
    try:
        results = search(" ".join(sys.argv[1:]))
        print(results)
    except Exception as e:
        print(f'Failed to search: {e}')
