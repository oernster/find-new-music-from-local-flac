# find-new-music-from-local-flac v1.0a
Finds local music from local FLAC music directory

There are two scripts to run in order...

1) musicdiscovery.py
2) spotifyclient.py

The first will create a json file of keys from your FLAC local library directory with a list of values containing inspired artists, avoiding copycat bands etc. and ensuring that no inspired artists are the same as your source artists from your local FLAC library.  This uses the [MusicBrainz developer API](https://musicbrainz.org/).

I have made sure that there is a 6 second delay between each artist lookup on the MusicBrainz API since it is rate limited.  You can reduce this value in the musicdiscovery.py script (there is a constant at the top of the file for it) and there is a fall back rate limiting timeout which will delay temporarily if it finds a rate limiting problem.  However, I've found 6s to be a workable number.

NOTE: If you have a large library like me (I have around 450 CDs ripped to FLAC) then the script will take a while to run; however, I have ensured it reports in colour on the command prompt, information about it's progress so you can understand what is going on.

The second will create, based on the inspired artists lists (10 max, though this is configurable in the first script), spotify playlists based on genre.

If you want to subsequently NOT use spotify (use the free service instead) and use a decent FLAC music source or other service, then I can recommend installing [FreeYourMusic](https://freeyourmusic.com/) to transfer your spotify playlists to your desired streaming service.  I use [Deezer](https://www.deezer.com/en/) myself.

The Deezer App doesn't support API usage currently for developers so this has to be a manual step via a service like Spotify as the initial playlist generating step; hence my approach. 

### Before you start:

- Rip CDs to FLAC format and store them all in one super directory with subdirectories labelled by artist name; this should be done automatically by most CD rippers.
- Create a Spotify account and go to the spotify developer API portal and login.  Then create an app.  In settings, specify the callback as http://127.0.0.1:8888/callback and tick the Web API and Web Playback SDK options.
- Go to settings and get your spotify client id and client secret and paste them into spotifyclient.py.
- Create a musicbrainz account and put your email as a courtesy in the musicbrainz.py file.

### Installation

- Requires Windows for the selecting of directories and files in file explorer for FLAC music directory selection and json file selection after 1st step.  Comment this code and adjust to your needs if on linux/mac
- Install Python 3 of some variety
- Install git
- Launch a terminal or powershell
- Clone the repo: ```git clone https://github.com/oernster/find-new-music-from-local-flac.git``` - this will create a subdirectory in whatever location you are in when you run the command with the contents of this repository.
- Create a virtual environment: ```python -m venv venv```
- Activate it: ```venv\scripts\activate``` on windows or on linux/mac: ```source venv/bin/activate```
- Install dependencies: ```pip install -r requirements.txt```
- Upgrade pip to latest if needed: ```python -m pip install --upgrade pip```

## How to run

- ```python musicdiscovery.py``` - Select your FLAC directory.  Now be patient as this may take a while depending on the size of your library but it will create a json file in the directory that you cloned the repo into that contains keys as your FLAC artist names and a list of values which are the inspired artists.
- ```python spotifyclient.py``` - Select your json generated file.  This will generate numbered playlists, currently with basic names but later, when I upgrade the code, based on genre, still numbered and it the playlists will be generated with top tracks by your inspired artists; 50-100 tracks per playlist. 
