"""
refreshToken.py

Non-interactive refresh of the long-lived Instagram access token in
token.json. Instagram allows refreshing a long-lived token that is at
least 24 hours old and not yet expired, extending it another ~60 days -
no browser login required, unlike getAccessToken.py.

Run automatically by the GitHub Actions workflow before each scheduled
pull, so the token effectively never expires as long as the workflow keeps
running at least once every ~60 days. Can also be run standalone locally.

If the refresh call fails (e.g. the token has already fully expired and is
past the point Instagram will refresh it), this leaves token.json
untouched and exits without error, so a scheduled pull still gets a chance
to run with whatever token is currently on file rather than aborting the
whole workflow over a refresh hiccup.

Run with:
  python refreshToken.py
"""

import json
from datetime import datetime, timedelta

import requests

REFRESH_ENDPOINT = "https://graph.instagram.com/refresh_access_token"


def loadTokenRecord(tokenPath="token.json"):
    with open(tokenPath, "r") as tokenFile:
        return json.load(tokenFile)


def saveTokenRecord(tokenRecord, outputPath="token.json"):
    with open(outputPath, "w") as tokenFile:
        json.dump(tokenRecord, tokenFile, indent=2)


def refreshAccessToken(currentAccessToken):
    """Exchange a still-valid long-lived token for a fresh one with a new ~60-day expiry."""
    response = requests.get(
        REFRESH_ENDPOINT,
        params={"grant_type": "ig_refresh_token", "access_token": currentAccessToken},
    )
    response.raise_for_status()
    responseData = response.json()
    return responseData["access_token"], responseData["expires_in"]


def main():
    tokenRecord = loadTokenRecord()

    try:
        newAccessToken, expiresInSeconds = refreshAccessToken(tokenRecord["accessToken"])
    except requests.exceptions.RequestException as error:
        print(f"Token refresh failed, leaving token.json unchanged: {error}")
        return

    expiryDate = datetime.now() + timedelta(seconds=expiresInSeconds)
    tokenRecord["accessToken"] = newAccessToken
    tokenRecord["obtainedAt"] = datetime.now().isoformat()
    tokenRecord["expiresAt"] = expiryDate.isoformat()

    saveTokenRecord(tokenRecord)
    print(f"Token refreshed. New expiry: {expiryDate.strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()
