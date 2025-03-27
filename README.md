# find-new-music-from-local-flac
Finds local music from local FLAC music directory

There are two scripts to run in order...

1) musicdiscovery.py
2) spotifyclient.py

The first will create a json file of keys from your FLAC local library directory with a list of values containing inspired artists, avoiding copycat bands etc..  This uses the MusicBrainz developer API.

The second will create, based on the inspired artists lists (10 max, though this is configurable in the first script), spotify playlists based on genre.

If you want to subsequently NOT use spotify (use the free service instead) and use a decent FLAC music source or other service, then I can recommend installing [FreeYourMusic](https://freeyourmusic.com/) to transfer your spotify playlists to your desired streaming service.

The Deezer App doesn't support API usage currently for developers so this has to be a manual step via a service like Spotify as the initial playlist generating step; hence my approach. 
