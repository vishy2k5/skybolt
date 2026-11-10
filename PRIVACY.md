# Skybolt privacy policy

Skybolt is a personal, self-hosted family wall calendar. It runs on the owner's own Raspberry Pi and is not offered as a service to anyone else.

## What Skybolt accesses
With your permission, Skybolt uses the Google Calendar API to read, create, edit and delete events in your Google calendars, so it can show them on the wall display and keep them in sync.

## Where your data goes
- Calendar, chore and family-member data, and any photos you add for the screensaver, are stored only on the device running Skybolt. Photos are shown from resized copies with all metadata (including location) removed; your originals are not changed or sent anywhere.
- Skybolt contacts only two outside services:
  - **Google**, through its Calendar API, only after you connect your account.
  - **[Open-Meteo](https://open-meteo.com/)**, to fetch the weather. This request contains the latitude and longitude you configured, and nothing else. No account or API key is involved.
- There are no analytics, ads or tracking, and no data is sent to the developer or to any other server.
- Your Google sign-in token is stored encrypted on that device and is never shared.
- Skybolt's use of information received from Google APIs follows the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Removing access
Disconnect Google in Skybolt's Settings, or remove "Skybolt" at https://myaccount.google.com/permissions. Either one stops all access. To remove all stored data, delete the `data/` folder on the device.

## Contact
Open an issue at https://github.com/vishy2k5/skybolt.
