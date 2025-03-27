# find-new-music-from-local-flac
Finds local music from local FLAC music directory

There are two scripts to run in order...

1) musicdiscovery.py
2) spotifyclient.py

The first will create a json file of keys from your FLAC local library directory with a list of values containing inspired artists, avoiding copycat bands etc..  This uses the [MusicBrainz developer API](https://musicbrainz.org/).

I have made sure that there is a 6 second delay between each artist lookup on the MusicBrainz API since it is rate limited.  You can reduce this value in the musicdiscovery.py script (there is a constant at the top of the file for it) and there is a fall back rate limiting timeout which will delay temporarily if it finds a rate limiting problem.  However, I've found 6s to be a workable number.

NOTE: If you have a large library like me (I have around 450 CDs ripped to FLAC) then the script will take a while to run; however, I have ensured it reports in colour on the command prompt, information about it's progress so you can understand what is going on.

The second will create, based on the inspired artists lists (10 max, though this is configurable in the first script), spotify playlists based on genre.

If you want to subsequently NOT use spotify (use the free service instead) and use a decent FLAC music source or other service, then I can recommend installing [FreeYourMusic](https://freeyourmusic.com/) to transfer your spotify playlists to your desired streaming service.  I use [Deezer](https://www.deezer.com/en/) myself.

The Deezer App doesn't support API usage currently for developers so this has to be a manual step via a service like Spotify as the initial playlist generating step; hence my approach. 
