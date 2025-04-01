# Playlist Generator v2.5
- UI overhauled and made dark theme, correctly functioning colour changing progress bars, and correctly generating top tracks in playlists in _relevant_ playlist genres.  Also, 3 times faster while respecting rate limiting constraints for 3rd party APIs.

# Discover new music with generated new artists top tracks playlists from your local music organised by genre!!!

The UI/exe once generated will (Step 1) create a json file of keys from your local library directory with a list of values containing inspired artists, avoiding copycat bands etc. and ensuring that no inspired artists are the same as your source artists from your local FLAC library.  This uses the [MusicBrainz developer API](https://musicbrainz.org/).

NOTE: If you have a large library like me (I have around 450 CDs ripped to FLAC (Free Lossless Audio Codec; basically as good as CD), though mp3 or wav should work fine too since it uses directory names) then the script will take a while to run.

The second button will create, based on the inspired artists lists (json file), spotify playlists based on genre.

If you want to subsequently NOT use spotify (use the free service instead) and use a decent FLAC music source or other service, then I can recommend installing [TuneMyMusic](https://www.tunemymusic.com/) to transfer your spotify playlists to your desired streaming service.  I use [Deezer](https://www.deezer.com/en/) myself.

The Deezer App doesn't support API usage currently for developers so this has to be a manual step via a service like Spotify as the initial playlist generating step; hence my approach. 

### Before you start:

- Rip CDs to FLAC format and store them all in one super directory with subdirectories labelled by artist name; this should be done automatically by most CD rippers.
- Create a Spotify account and go to the spotify developer API portal and login.  Then create an app.  In settings, specify the callback as `http://127.0.0.1:8888/callback` and tick the Web API and Web Playback SDK options.
- Go to settings and get your spotify client id and client secret and paste them into spotifyclient.py in the class `SpotifyPlaylistManager`, method named `create_spotify_client`.
- Create a musicbrainz account and put your email as a courtesy in the musicbrainz.py file in the `__init__` constructor method in the class `MusicBrainzAPI`.

### Installation

- Requires Windows for the selecting of directories and files in file explorer for FLAC music directory selection and json file selection after 1st step.  Comment this code and adjust to your needs if on linux/mac
- Install Python 3 of some variety
- Install git
- Launch a terminal or powershell
- Clone the repo: ```git clone https://github.com/oernster/playlist-generator.git``` - this will create a subdirectory in whatever location you are in when you run the command with the contents of this repository.
- Create a virtual environment: ```python -m venv venv```
- Activate it: ```venv\scripts\activate``` on windows or on linux/mac: ```source venv/bin/activate```
- Install dependencies: ```pip install -r requirements.txt```
- Upgrade pip to latest if needed: ```python -m pip install --upgrade pip```

## How to create the exe

- ```python buildexe.py``` - This will create an executable file runnable on Windows in a subdirectory called dist.
- Run the `PlaylistGenerator.exe` created program.
