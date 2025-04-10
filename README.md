![GenreGeniusIcon](https://github.com/user-attachments/assets/dbec7b04-612b-4b25-872f-4e4269773362) GenreGenius version 1.4.1

- Discover new music with generated new artists top tracks playlists from your local music organised by genre!!!
- (currently only supported on Windows; with enough monetary contributions, I may provide a port to at least Debian Linux; can't afford a mac right now so... meh!)

## If you find this GenreGenius app of use and would like to offer me a contribution for enhancing and maintaining it then please use this link:

### [Expected contribution here](https://www.paypal.com/ncp/payment/6KFFAMLY8H9ZS)

The UI/exe once generated will (Step 1) create a json file of keys from your local library directory with a list of values containing inspired artists, avoiding copycat bands etc..  This uses the [MusicBrainz developer API](https://musicbrainz.org/).

NOTE: If you have a large library like me (I have around 450 CDs ripped to FLAC (Free Lossless Audio Codec; basically as good as CD), though mp3 or wav should work fine too since it uses directory names as the artists in subdirectories of the main music directory chosen) then the script will take a while to run.

The second button will create, based on the inspired artists lists (recommendations.json file), spotify playlists based on genre.

If you want to subsequently NOT use spotify (use the free service instead) and use a decent FLAC music source or other service, then I can recommend installing [TuneMyMusic](https://www.tunemymusic.com/) to transfer your spotify playlists to your desired streaming service.  I use [Deezer](https://www.deezer.com/en/) myself.
If you mess up and need to delete your playlists from a streaming service by bulk, then consider [Soundiiz](https://soundiiz.com/) - you can create a free account and handle that with that site.

The Deezer App doesn't support API usage currently for developers so this has to be a manual step via a service like Spotify as the initial playlist generating step; hence my approach.

### Before you start:

- Rip CDs to FLAC/other format and store them all in one super directory (or buy your music digitally) with subdirectories labelled by artist name; this should be done automatically by most CD rippers.
- Create a Spotify account and go to the [spotify developer API portal](https://developer.spotify.com/documentation/web-api) and login.  Then create an app.  In settings, specify the callback as `http://127.0.0.1:8888/callback` and tick the Web API and Web Playback SDK options.  This step is necessary to associate client and secret keys with your Spotify account. 
- Create a musicbrainz account.

### Installation

- Requires Windows for the UI.
- Install [Python 3](https://www.python.org/)
- Install [git](https://gitforwindows.org/)
- Launch a terminal or powershell
- Clone the repo: ```git clone https://github.com/oernster/playlist-generator.git``` - this will create a subdirectory in whatever location you are in when you run the command with the contents of this repository.
- Create a virtual environment: ```python -m venv venv```
- Activate it: ```venv\scripts\activate```
- Install dependencies: ```pip install -r requirements.txt```
- Upgrade pip to latest: ```python -m pip install --upgrade pip```

## How to create the exe

- ```python buildexe.py``` - This will create an executable file runnable on Windows in a subdirectory called dist.

## Running

- Run the `GenreGenius.exe` created program.
- Hit the Step 1 button; fill in credentials.
- Hit the step 2 button.

# Note 
- Step 1 takes the longest time (Primary artist lookups followed by Various Artists lookups if appropriate).  
- Step 2 also takes a some time depending on the number of artists generated but not so long (Artist genre lookup, followed by classification into genres and playlist(s) generation).
