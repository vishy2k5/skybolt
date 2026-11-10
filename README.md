# skybolt
A smart Home Calendar that is more than just a calendar

Python project managed with [uv](https://docs.astral.sh/uv/).

## Run locally
```
./run.sh            # starts http://127.0.0.1:8000 (installs deps on first run)
./run.sh seed       # in another terminal: load demo data (once)
uv run pytest       # tests
```
API docs: http://127.0.0.1:8000/docs
Screens can be opened directly: `/?view=month`, `/?open=weather`, `/?open=chores`, `/?open=settings`, `/?open=add`.
Weather location: set `SKYBOLT_LAT`, `SKYBOLT_LON`, `SKYBOLT_UNITS` in `.env` (see `.env.example`).

## Google Calendar
Two-way sync with your Google calendars, using your own Google Cloud project so no other service sees your data.
To connect, open http://localhost:8000 on the Pi, go to **Settings > Google Calendar** and follow the five steps shown there. You'll create a free Google Cloud project with a **Desktop app** client, then paste its Client ID and secret.
Sign-in details are stored encrypted in `data/`. Edits on the wall reach Google within seconds, and changes from a phone show up within 2 minutes.

## Deploy on the Pi
Requires Raspberry Pi OS with the desktop (labwc), Chromium and [uv](https://docs.astral.sh/uv/).
```
deploy/install.sh backend     # systemd service on 127.0.0.1:8000, starts at boot
deploy/install.sh kiosk-on    # full-screen browser now and at every desktop login
deploy/install.sh kiosk-off   # back to the normal desktop
deploy/install.sh uninstall   # removes the services, keeps data/
```
The kiosk takes over the screen, so leave it off while using the Pi as a desktop. Closing the browser only reloads it, so use `kiosk-off` to exit. It also restarts nightly at 04:00.

For a wall display, turn on desktop auto-login: `sudo raspi-config nonint do_boot_behaviour B4`.

On-screen keyboard (needed to type on the touchscreen): `sudo apt install squeekboard`, then reboot. The kiosk passes `--enable-wayland-ime` so Chromium shows it when a text field is tapped. If it does not appear, check `raspi-config` under Display Options for the on-screen keyboard setting.

Logs: `journalctl -u skybolt -f`. After changing `.env` or pulling new code: `sudo systemctl restart skybolt`.

The API has no authentication yet, so keep `SKYBOLT_HOST=127.0.0.1` unless you trust everything on your network.

## License

Source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE). Free to use, modify and share for personal, hobby, research and other noncommercial purposes. Commercial use is not permitted.
