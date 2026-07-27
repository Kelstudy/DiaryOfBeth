"""
getAccessToken.py

One-time (or occasional re-auth) script for the Instagram API with Instagram Login.

What it does:
  1. Builds an authorization URL and asks you to open it in a browser.
  2. You log in as thediaryofbeth and approve the requested permissions.
  3. Instagram redirects you to your redirect URI with a ?code=... in the URL.
     Copy that FULL URL from your browser's address bar and paste it back here.
  4. The script exchanges that code for a short-lived (~1 hour) access token.
  5. It then exchanges the short-lived token for a long-lived (~60 day) token.
  6. The long-lived token + its expiry date get saved to token.json locally.

Run this again whenever you need a brand new token from scratch (e.g. if a
refresh has been missed and the old token has fully expired). For routine
refreshing before the 60-day expiry, use refreshToken.py instead - that one
does not require you to re-authorize in a browser.

Requires a .env file (never committed to git) with:
  INSTAGRAM_APP_ID=your_app_id
  INSTAGRAM_APP_SECRET=your_app_secret
  INSTAGRAM_REDIRECT_URI=https://localhost/
"""

import os
import json
import urllib.parse
import requests
from dotenv import load_dotenv


def loadCredentials():
    """Load app credentials from .env and confirm none are missing."""
    load_dotenv()

    appId = os.getenv("INSTAGRAM_APP_ID")
    appSecret = os.getenv("INSTAGRAM_APP_SECRET")
    redirectUri = os.getenv("INSTAGRAM_REDIRECT_URI")

    missingVars = [
        name
        for name, value in [
            ("INSTAGRAM_APP_ID", appId),
            ("INSTAGRAM_APP_SECRET", appSecret),
            ("INSTAGRAM_REDIRECT_URI", redirectUri),
        ]
        if not value
    ]

    if missingVars:
        raise RuntimeError(
            f"Missing required .env variables: {', '.join(missingVars)}. "
            "Create a .env file in this folder before running the script."
        )

    return appId, appSecret, redirectUri


def buildAuthorizationUrl(appId, redirectUri):
    """Build the URL the user visits to log in and grant permissions."""
    requestedScopes = [
        "instagram_business_basic",
        "instagram_business_manage_insights",
    ]

    queryParams = {
        "client_id": appId,
        "redirect_uri": redirectUri,
        "response_type": "code",
        "scope": ",".join(requestedScopes),
    }

    return "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode(queryParams)


def extractCodeFromRedirect(pastedUrl):
    """Pull the authorization code out of the URL the user pastes back."""
    parsedUrl = urllib.parse.urlparse(pastedUrl)
    queryDict = urllib.parse.parse_qs(parsedUrl.query)

    if "code" not in queryDict:
        raise ValueError(
            "Could not find a 'code' parameter in that URL. "
            "Make sure you copied the full address bar URL after logging in."
        )

    rawCode = queryDict["code"][0]

    # Instagram sometimes appends a trailing '#_' fragment to the redirect.
    # That fragment is not part of the code itself, so strip it off if present.
    cleanCode = rawCode.split("#")[0]

    return cleanCode


def exchangeCodeForShortLivedToken(appId, appSecret, redirectUri, authorizationCode):
    """Exchange the one-time authorization code for a short-lived access token."""
    tokenEndpoint = "https://api.instagram.com/oauth/access_token"

    formData = {
        "client_id": appId,
        "client_secret": appSecret,
        "grant_type": "authorization_code",
        "redirect_uri": redirectUri,
        "code": authorizationCode,
    }

    response = requests.post(tokenEndpoint, data=formData, timeout=30)
    response.raise_for_status()
    responseData = response.json()

    # The API can return either a flat object or a {"data": [...]} wrapper
    # depending on the exact endpoint version, so handle both shapes.
    if "data" in responseData:
        tokenInfo = responseData["data"][0]
    else:
        tokenInfo = responseData

    return tokenInfo["access_token"], tokenInfo["user_id"]


def exchangeForLongLivedToken(appSecret, shortLivedToken):
    """Exchange a short-lived token for a 60-day long-lived token."""
    exchangeEndpoint = "https://graph.instagram.com/access_token"

    queryParams = {
        "grant_type": "ig_exchange_token",
        "client_secret": appSecret,
        "access_token": shortLivedToken,
    }

    response = requests.get(exchangeEndpoint, params=queryParams, timeout=30)
    response.raise_for_status()
    responseData = response.json()

    return responseData["access_token"], responseData["expires_in"]


def saveTokenToFile(longLivedToken, expiresInSeconds, userId, outputPath="token.json"):
    """Save the long-lived token locally so other scripts can read it."""
    import datetime

    expiryDate = datetime.datetime.now() + datetime.timedelta(seconds=expiresInSeconds)

    tokenRecord = {
        "accessToken": longLivedToken,
        "userId": userId,
        "obtainedAt": datetime.datetime.now().isoformat(),
        "expiresAt": expiryDate.isoformat(),
    }

    with open(outputPath, "w") as tokenFile:
        json.dump(tokenRecord, tokenFile, indent=2)

    return outputPath, expiryDate


def main():
    appId, appSecret, redirectUri = loadCredentials()

    authorizationUrl = buildAuthorizationUrl(appId, redirectUri)

    print("\nStep 1: Open this URL in your browser and log in as your Instagram account:\n")
    print(authorizationUrl)
    print(
        "\nAfter approving, you'll land on a page that may show an error "
        "(that's expected if your redirect URI isn't a real live page) - "
        "what matters is the URL in the address bar. Copy that full URL.\n"
    )

    pastedRedirectUrl = input("Step 2: Paste the full redirect URL here: ").strip()

    authorizationCode = extractCodeFromRedirect(pastedRedirectUrl)
    print("\nExtracted authorization code successfully.")

    shortLivedToken, userId = exchangeCodeForShortLivedToken(
        appId, appSecret, redirectUri, authorizationCode
    )
    print("Exchanged code for a short-lived token.")

    longLivedToken, expiresInSeconds = exchangeForLongLivedToken(appSecret, shortLivedToken)
    print("Exchanged short-lived token for a long-lived (60-day) token.")

    outputPath, expiryDate = saveTokenToFile(longLivedToken, expiresInSeconds, userId)

    print(f"\nSaved token to {outputPath}")
    print(f"Instagram user ID: {userId}")
    print(f"This token expires around: {expiryDate.strftime('%Y-%m-%d %H:%M')}")
    print(
        "\nReminder: token.json contains a live access token. "
        "Make sure it's listed in .gitignore and never gets committed."
    )


if __name__ == "__main__":
    main()
