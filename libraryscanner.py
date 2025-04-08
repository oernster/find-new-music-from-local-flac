"""
Library scanner module for scanning FLAC music libraries and extracting artist information.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple
from pathlib import Path
import os
from collections import Counter
from colorama import Fore, Style
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
import mutagen

class MusicLibraryScanner(ABC):
    """Abstract base class for music library scanners."""
    
    @abstractmethod
    def scan(self) -> List[Tuple[str, int]]:
        """
        Scan the music library and return a list of (artist_name, count) tuples
        sorted by frequency (most frequent first).
        
        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        pass


class FlacLibraryScanner(MusicLibraryScanner):
    """Scanner for FLAC music libraries."""
    
    def __init__(self, music_dir: str, min_artist_count: int = 1):
        """
        Initialize the FLAC library scanner.
        
        Args:
            music_dir (str): Directory containing FLAC music files
            min_artist_count (int): Minimum number of songs by an artist to include them
        """
        self.music_dir = Path(music_dir)
        self.min_artist_count = min_artist_count
    
    def _extract_artists_from_compilation(self, flac_file_path: str) -> List[str]:
        """
        Extract artists from a compilation album, handling various edge cases.
        
        Args:
            flac_file_path (str): Full path to the FLAC file in a compilation
        
        Returns:
            List[str]: List of artist names extracted from the file
        """
        try:
            # Read the FLAC file
            audio = FLAC(flac_file_path)
            
            # Compilation artist tag variations to look for and filter out
            various_artists_variations = [
                'various artists', 'various', 'va', 'v.a.', 
                'compilation', 'soundtracks', 'ost'
            ]
            
            # Tag priority for artist extraction
            tag_priority = [
                'artist', 
                'albumartist', 
                'performer', 
                'composer', 
                'album_artist'
            ]
            
            extracted_artists = []
            
            # Try each tag in priority order
            for tag in tag_priority:
                if tag in audio:
                    artist_names = audio[tag]
                    
                    # Filter out Various Artists placeholders
                    filtered_artists = [
                        name.strip() for name in artist_names 
                        if name.strip().lower() not in various_artists_variations and 
                           'various' not in name.lower() and 
                           not name.lower().startswith('v.a.')
                    ]
                    
                    # If we found valid artists, use them
                    if filtered_artists:
                        extracted_artists.extend(filtered_artists)
                        break
            
            # Fallback: Try extracting from title if no artists found
            if not extracted_artists and 'title' in audio:
                title = audio['title'][0]
                # Check if title follows "Artist - Title" format
                if ' - ' in title:
                    potential_artist = title.split(' - ')[0].strip()
                    if potential_artist.lower() not in various_artists_variations:
                        extracted_artists.append(potential_artist)
            
            return extracted_artists
        
        except Exception as e:
            print(f"{Fore.YELLOW}Error extracting artists from compilation file {flac_file_path}: {e}{Style.RESET_ALL}")
            return []
    
    def _get_album_artist_directory(self, flac_file_path: str) -> str:
        """
        Intelligently determine the correct artist directory for a FLAC file,
        with special handling for compilation and various artists albums.
        
        Args:
            flac_file_path (str): Full path to the FLAC file
        
        Returns:
            str: Path to the appropriate artist directory
        """
        # Get immediate directory and parent directory
        file_dir = os.path.dirname(flac_file_path)
        parent_dir = os.path.basename(file_dir)
        grandparent_dir = os.path.dirname(file_dir)
        
        # List of variations of "Various Artists" directories to check
        various_artists_variations = [
            'various artists', 'various', 'va', 'v.a.', 
            'compilation', 'soundtracks', 'ost'
        ]
        
        # Check if the current or parent directory is a "Various Artists" type directory
        is_various_artists_dir = (
            parent_dir.lower() in various_artists_variations or 
            any(va in parent_dir.lower() for va in various_artists_variations)
        )
        
        # If it's a Various Artists directory, step up
        if is_various_artists_dir:
            try:
                # Try to read artist information from the FLAC file
                audio = FLAC(flac_file_path)
                
                # Check various artist tags
                artist_tags = []
                tag_priority = [
                    'artist', 
                    'albumartist', 
                    'performer', 
                    'composer', 
                    'album_artist'
                ]
                
                for tag in tag_priority:
                    if tag in audio:
                        artist_names = audio[tag]
                        # Filter out Various Artists placeholders
                        artist_names = [
                            name for name in artist_names 
                            if name.lower() not in various_artists_variations and 
                               'various' not in name.lower() and 
                               not name.lower().startswith('v.a.')
                        ]
                        
                        if artist_names:
                            artist_tags = artist_names
                            break
                
                # If we found an artist, try to create a directory name
                if artist_tags:
                    # Use the first valid artist name
                    primary_artist = artist_tags[0].strip()
                    
                    # Create a safe directory name by removing special characters
                    safe_artist_name = ''.join(
                        char for char in primary_artist 
                        if char.isalnum() or char in [' ', '-', '_']
                    ).strip()
                    
                    # Look for a directory with this artist name in the parent directories
                    current_search_dir = grandparent_dir
                    while current_search_dir and len(current_search_dir) > len(str(self.music_dir)):
                        potential_artist_dir = os.path.join(current_search_dir, safe_artist_name)
                        if os.path.isdir(potential_artist_dir):
                            return potential_artist_dir
                        
                        # Move up one directory
                        current_search_dir = os.path.dirname(current_search_dir)
            
            except Exception as e:
                print(f"{Fore.YELLOW}Error extracting artist from FLAC file: {e}{Style.RESET_ALL}")
        
        # If no special handling is needed or failed, return the parent directory
        return file_dir
    
    def scan_with_musicbrainz(self) -> List[Tuple[str, int]]:
        """
        Scan the music library for audio files and extract artists,
        with enhanced handling of Various Artists compilations using MusicBrainz.
        
        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        print(f"{Fore.CYAN}Scanning music library in {self.music_dir}...{Style.RESET_ALL}")
        artists = []
        processed_files = 0
        skipped_files = 0
        
        # Store compilation albums with their track artists
        compilation_albums = {}  # Maps album name to set of track artist names
        
        # Store individual files for each album to avoid scanning multiple times
        album_files = {}  # Maps album name to list of file paths
        
        # Comprehensive list of audio file extensions
        AUDIO_EXTENSIONS = [
            # Lossless formats
            '.flac', '.alac', '.wav', '.aiff', '.aif', '.aifc', 
            '.wv',   # WavPack
            '.ape',  # Monkey's Audio
            '.tak',  # Tom's lossless Audio Kompressor
            
            # Lossy formats
            '.mp3', '.m4a', '.aac', '.ogg', '.opus', 
            '.wma', '.webm', 
            
            # Less common formats
            '.ac3', '.mka',  # Matroska Audio
            '.ra', '.ram',   # RealAudio
            '.mid', '.midi', # MIDI files
            '.caf'           # Apple Core Audio Format
        ]

        # First pass: identify all albums and their artists
        for root, _, files in os.walk(self.music_dir):
            audio_files = [f for f in files if any(f.lower().endswith(ext) for ext in AUDIO_EXTENSIONS)]
            if not audio_files:
                continue
                
            for file in audio_files:
                try:
                    file_path = os.path.join(root, file)
                    
                    # Skip invalid files
                    if os.path.getsize(file_path) < 128:
                        skipped_files += 1
                        continue
                        
                    # Read the audio file using appropriate method
                    try:
                        # Select appropriate Mutagen method based on file extension
                        if file.lower().endswith('.flac'):
                            audio_file = FLAC(file_path)
                        elif file.lower().endswith('.mp3'):
                            audio_file = MP3(file_path)
                        elif file.lower().endswith(('.m4a', '.mp4')):
                            audio_file = MP4(file_path)
                        else:
                            # Use mutagen for other formats
                            audio_file = mutagen.File(file_path)
                        
                        # Skip if no tags found
                        if not audio_file:
                            skipped_files += 1
                            continue
                        
                        processed_files += 1
                        
                        # Extract album name from tags
                        album_name = "Unknown Album"
                        if 'album' in audio_file:
                            album_name = audio_file['album'][0]
                        
                        # Add file to album_files for later processing
                        if album_name not in album_files:
                            album_files[album_name] = []
                        album_files[album_name].append(file_path)
                        
                        # Detect Various Artists compilation
                        is_compilation = False
                        compilation_indicators = ('various artists', 'various', 'va', 'v.a.')
                        
                        # Check artist tags for Various Artists indicators
                        artist_tags = ['artist', 'albumartist']
                        for tag in artist_tags:
                            if tag in audio_file:
                                if any(va in str(artist).lower() for va in compilation_indicators for artist in audio_file[tag]):
                                    is_compilation = True
                                    break
                        
                        # Check directory for Various Artists indicators
                        if not is_compilation and any(va in root.lower() for va in compilation_indicators):
                            is_compilation = True
                        
                        # Extract artists
                        if is_compilation:
                            # Initialize the album in compilation tracking
                            if album_name not in compilation_albums:
                                compilation_albums[album_name] = set()
                            
                            # Try to extract artists from various tags
                            artist_extraction_tags = [
                                'artist', 
                                'performer', 
                                'composer', 
                                'title'
                            ]
                            
                            for tag in artist_extraction_tags:
                                if tag in audio_file:
                                    for artist_candidate in audio_file[tag]:
                                        # Clean and validate artist
                                        if isinstance(artist_candidate, str):
                                            artist = artist_candidate.strip()
                                            
                                            # Skip Various Artists indicators
                                            if artist.lower() not in compilation_indicators:
                                                # Special handling for "Artist - Title" format
                                                if tag == 'title' and ' - ' in artist:
                                                    artist = artist.split(' - ')[0].strip()
                                                
                                                if artist:
                                                    artists.append(artist)
                                                    compilation_albums[album_name].add(artist)
                        else:
                            # Normal track artist extraction
                            if 'artist' in audio_file:
                                for artist in audio_file['artist']:
                                    if isinstance(artist, str) and artist.lower() not in compilation_indicators:
                                        artists.append(artist)
                    
                    except Exception as e:
                        skipped_files += 1
                        if "not a valid audio file" not in str(e).lower():
                            print(f"{Fore.RED}Error processing {file}: {e}{Style.RESET_ALL}")
                
                except Exception as e:
                    skipped_files += 1
                    if "not a valid file" not in str(e).lower():
                        print(f"{Fore.RED}Error processing {file}: {e}{Style.RESET_ALL}")
            
            # Second pass: Use MusicBrainz for compilations with missing artists
            try:
                # Initialize MusicBrainz API
                from musicbrainz import MusicBrainzAPI
                mb_api = MusicBrainzAPI()
                
                # Process each compilation album
                for album_name, track_artists in compilation_albums.items():
                    # Skip albums where we already have artists
                    if track_artists:
                        print(f"{Fore.GREEN}Album '{album_name}' already has {len(track_artists)} artists from file tags{Style.RESET_ALL}")
                        continue
                        
                    print(f"{Fore.YELLOW}Album '{album_name}' has no artists from tags, using MusicBrainz lookup{Style.RESET_ALL}")
                    
                    # Use MusicBrainz to look up album artists
                    mb_artists = mb_api.get_album_artists(album_name)
                    
                    # Add the artists to our lists
                    for artist in mb_artists:
                        if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                            artists.append(artist)
                            track_artists.add(artist)
                    
                    print(f"{Fore.GREEN}Added {len(mb_artists)} artists from MusicBrainz for album '{album_name}'{Style.RESET_ALL}")
                    
                    # Respect API rate limits
                    time.sleep(2)
                        
            except Exception as e:
                print(f"{Fore.RED}Error using MusicBrainz: {e}{Style.RESET_ALL}")
            
            # Count occurrences of each artist and sort by frequency
            artist_counter = Counter(artists)
            
            # Filter out Various Artists entries and other common compilation placeholders
            for va in ('various artists', 'various', 'va', 'v.a.', 'soundtrack', 'original soundtrack'):
                if va in artist_counter:
                    del artist_counter[va]
            
            # Filter to include only artists with at least min_artist_count songs
            filtered_artists = {artist: count for artist, count in artist_counter.items() 
                               if count >= self.min_artist_count}
            
            sorted_artists = sorted(filtered_artists.items(), key=lambda x: x[1], reverse=True)
            
            print(f"{Fore.GREEN}Found {len(sorted_artists)} unique artists in {processed_files} valid audio files.{Style.RESET_ALL}")
            
            if sorted_artists:
                # Show sample artists for validation
                print(f"{Fore.GREEN}Sample artists in library: {', '.join([a[0] for a in sorted_artists[:5]])}{Style.RESET_ALL}")
                
                print(f"{Fore.GREEN}Top 10 artists: {', '.join([a[0] for a in sorted_artists[:10]])}{Style.RESET_ALL}")
            
            if skipped_files > 0:
                print(f"{Fore.YELLOW}Skipped {skipped_files} invalid or problematic files.{Style.RESET_ALL}")
                
            # Store compilation albums for later use
            self.compilation_albums = compilation_albums
            
            print(f"{Fore.GREEN}Returning all {len(sorted_artists)} artists{Style.RESET_ALL}")
            return sorted_artists
    
    def scan(self) -> List[Tuple[str, int]]:
        """
        Scan the music library for audio files and extract artists.
        Enhanced with directory-based artist extraction.

        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        print(f"{Fore.CYAN}Scanning music library in {self.music_dir}...{Style.RESET_ALL}")
        artists = []
        processed_files = 0
        skipped_files = 0

        # Comprehensive list of audio file extensions
        AUDIO_EXTENSIONS = [
            # Lossless formats
            '.flac', '.alac', '.wav', '.aiff', '.aif', '.aifc', 
            '.wv',   # WavPack
            '.ape',  # Monkey's Audio
            '.tak',  # Tom's lossless Audio Kompressor
            
            # Lossy formats
            '.mp3', '.m4a', '.aac', '.ogg', '.opus', 
            '.wma', '.webm', 
            
            # Less common formats
            '.ac3', '.mka',  # Matroska Audio
            '.ra', '.ram',   # RealAudio
            '.mid', '.midi', # MIDI files
            '.caf'           # Apple Core Audio Format
        ]

        # Various Artists indicators
        VARIOUS_ARTISTS_INDICATORS = (
            'various artists', 'various', 'va', 'v.a.', 
            'compilation', 'soundtrack', 'ost'
        )

        try:
            # Scan the entire music directory
            for root, _, files in os.walk(self.music_dir):
                # Filter audio files
                audio_files = [f for f in files if any(f.lower().endswith(ext) for ext in AUDIO_EXTENSIONS)]
                
                if not audio_files:
                    continue
                
                for file in audio_files:
                    try:
                        file_path = os.path.join(root, file)
                        
                        # Skip very small files
                        if os.path.getsize(file_path) < 128:
                            skipped_files += 1
                            continue
                        
                        processed_files += 1
                        
                        # Extract artist from directory structure
                        # Look back two levels: artist directory is typically parent of album directory
                        path_parts = Path(file_path).parts
                        
                        # Determine potential artist name
                        if len(path_parts) >= 3:
                            potential_artist = path_parts[-3]
                            
                            # Skip if potential artist is a Various Artists indicator
                            if not any(indicator in potential_artist.lower() for indicator in VARIOUS_ARTISTS_INDICATORS):
                                # Only add if it's a meaningful artist name
                                if potential_artist and len(potential_artist) > 1:
                                    artists.append(potential_artist)
                    
                    except Exception as e:
                        skipped_files += 1
                        print(f"{Fore.RED}Error processing {file}: {e}{Style.RESET_ALL}")

        except Exception as e:
            print(f"{Fore.RED}Error scanning directory: {e}{Style.RESET_ALL}")

        # Count occurrences of each artist and sort by frequency
        artist_counter = Counter(artists)

        # Filter out Various Artists entries and other common compilation placeholders
        for va in VARIOUS_ARTISTS_INDICATORS:
            if va in artist_counter:
                del artist_counter[va]

        # Filter to include only artists with at least min_artist_count songs
        filtered_artists = {artist: count for artist, count in artist_counter.items() 
                           if count >= self.min_artist_count}

        sorted_artists = sorted(filtered_artists.items(), key=lambda x: x[1], reverse=True)

        print(f"{Fore.GREEN}Found {len(sorted_artists)} unique artists in {processed_files} valid audio files.{Style.RESET_ALL}")

        if sorted_artists:
            # Show sample artists for validation
            print(f"{Fore.GREEN}Sample artists in library: {', '.join([a[0] for a in sorted_artists[:5]])}{Style.RESET_ALL}")
            
            print(f"{Fore.GREEN}Top 10 artists: {', '.join([a[0] for a in sorted_artists[:10]])}{Style.RESET_ALL}")

        if skipped_files > 0:
            print(f"{Fore.YELLOW}Skipped {skipped_files} invalid or problematic files.{Style.RESET_ALL}")
            
        print(f"{Fore.GREEN}Returning all {len(sorted_artists)} artists{Style.RESET_ALL}")
        return sorted_artists


class ProgressTrackingFlacScanner(FlacLibraryScanner):
    """Extended FlacLibraryScanner with detailed progress tracking."""
    
    def __init__(self, music_dir: str, min_artist_count: int = 1):
        """
        Initialize the FLAC library scanner with progress tracking.
        
        Args:
            music_dir (str): Directory containing FLAC music files
            min_artist_count (int): Minimum number of songs by an artist to include them
        """
        super().__init__(music_dir, min_artist_count)
        self.total_subdirs = 0
        self.processed_subdirs = 0
        self.total_artist_dirs = 0
    
    def count_artist_directories(self) -> int:
        """
        Count the total number of subdirectories that might contain artist albums.
        
        Returns:
            int: Number of subdirectories
        """
        print(f"{Fore.CYAN}Counting artist directories in {self.music_dir}...{Style.RESET_ALL}")
        
        # Simple approach: count directories that contain FLAC files
        artist_dirs = set()
        total_subdirs = 0
        
        for root, _, files in os.walk(self.music_dir):
            # Convert to relative path from music_dir
            rel_path = os.path.relpath(root, self.music_dir)
            
            # Skip the root directory
            if rel_path == '.':
                continue
                
            # Count directories based on path depth
            # Typical structure: music_dir/artist/album
            path_parts = rel_path.split(os.sep)
            
            # First level directories are assumed to be artist directories
            if len(path_parts) == 1:
                artist_dirs.add(rel_path)
            
            # Count directories that might contain FLAC files (potential albums)
            if any(f.lower().endswith('.flac') for f in files):
                total_subdirs += 1
        
        self.total_artist_dirs = len(artist_dirs)
        self.total_subdirs = max(total_subdirs, 1)  # Avoid division by zero
        
        print(f"{Fore.GREEN}Found {self.total_artist_dirs} artist directories with {self.total_subdirs} potential album directories{Style.RESET_ALL}")
        return self.total_subdirs
    
    def scan(self) -> List[Tuple[str, int]]:
        """
        Scan the music library for FLAC files and extract artists with progress reporting.
        
        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        print(f"{Fore.CYAN}Scanning music library in {self.music_dir}...{Style.RESET_ALL}")
        
        # Count directories first
        self.count_artist_directories()
        
        artists = []
        processed_files = 0
        skipped_files = 0
        self.processed_subdirs = 0
        processed_dirs = set()
        various_artists_albums = set()
        
        try:
            # First pass: identify Various Artists compilations
            for root, _, files in os.walk(self.music_dir):
                flac_files = [f for f in files if f.lower().endswith('.flac')]
                if flac_files:
                    # Track progress by counting directories with FLAC files
                    rel_dir = os.path.relpath(root, str(self.music_dir))
                    if rel_dir not in processed_dirs:
                        processed_dirs.add(rel_dir)
                        self.processed_subdirs += 1
                        
                        # Report progress as percentage
                        progress_percent = (self.processed_subdirs / self.total_subdirs) * 100
                        print(f"Progress: {progress_percent:.1f}% ({self.processed_subdirs}/{self.total_subdirs} directories)")
                
                for file in flac_files:
                    try:
                        file_path = os.path.join(root, file)
                        flac_file = FLAC(file_path)
                        
                        if 'artist' in flac_file:
                            for artist in flac_file['artist']:
                                if artist.lower() in ('various artists', 'various', 'va', 'v.a.'):
                                    various_artists_albums.add(root)
                                    break
                    except Exception:
                        pass

            # Reset progress counter for second pass
            self.processed_subdirs = 0
            processed_dirs.clear()

            # Second pass: extract actual artists
            for root, _, files in os.walk(self.music_dir):
                flac_files = [f for f in files if f.lower().endswith('.flac')]
                
                if flac_files:
                    # Track progress by counting directories with FLAC files
                    rel_dir = os.path.relpath(root, str(self.music_dir))
                    if rel_dir not in processed_dirs:
                        processed_dirs.add(rel_dir)
                        self.processed_subdirs += 1
                        
                        # Report progress as percentage
                        progress_percent = (self.processed_subdirs / self.total_subdirs) * 100
                        print(f"Progress: {progress_percent:.1f}% ({self.processed_subdirs}/{self.total_subdirs} directories)")
                
                for file in files:
                    if file.lower().endswith('.flac'):
                        try:
                            file_path = os.path.join(root, file)
                            # Check if it's a valid FLAC file before attempting to read
                            if os.path.getsize(file_path) < 128:  # Minimum valid FLAC size
                                skipped_files += 1
                                continue
                                
                            flac_file = FLAC(file_path)
                            processed_files += 1
                            
                            # Handle "Various Artists" compilations specially
                            if root in various_artists_albums:
                                # For compilations, get artists from individual tracks
                                extracted = False
                                
                                # Try different tags for artist information
                                for tag in ['artist', 'albumartist', 'performer']:
                                    if tag in flac_file:
                                        for artist in flac_file[tag]:
                                            if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                                artists.append(artist)
                                                extracted = True
                                                
                                # Try composer if no other artist was found
                                if not extracted and 'composer' in flac_file:
                                    for composer in flac_file['composer']:
                                        artists.append(composer)
                            else:
                                # Normal case - just use the artist tag
                                if 'artist' in flac_file:
                                    for artist in flac_file['artist']:
                                        if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                            artists.append(artist)
                        except Exception as e:
                            skipped_files += 1
                            # Only print error for unexpected issues
                            if "not a valid FLAC file" not in str(e):
                                print(f"{Fore.RED}Error processing {file}: {e}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error scanning directory: {e}{Style.RESET_ALL}")
        
        # Report final progress
        print(f"Progress: 100.0% ({self.total_subdirs}/{self.total_subdirs} directories)")
        
        # Count occurrences of each artist and sort by frequency
        artist_counter = Counter(artists)
        
        # Filter out Various Artists entries and other common compilation placeholders
        for va in ('various artists', 'various', 'va', 'v.a.', 'soundtrack', 'original soundtrack'):
            if va in artist_counter:
                del artist_counter[va]
        
        # Filter to include only artists with at least min_artist_count songs
        filtered_artists = {artist: count for artist, count in artist_counter.items() 
                           if count >= self.min_artist_count}
        
        sorted_artists = sorted(filtered_artists.items(), key=lambda x: x[1], reverse=True)
        
        print(f"{Fore.GREEN}Found {len(sorted_artists)} unique artists in {processed_files} valid FLAC files.{Style.RESET_ALL}")
        
        if sorted_artists:
            # Show sample artists for validation
            print(f"{Fore.GREEN}Sample artists in library: {', '.join([a[0] for a in sorted_artists[:5]])}{Style.RESET_ALL}")
            
            print(f"{Fore.GREEN}Top 10 artists: {', '.join([a[0] for a in sorted_artists[:10]])}{Style.RESET_ALL}")
        
        if skipped_files > 0:
            print(f"{Fore.YELLOW}Skipped {skipped_files} invalid or problematic files.{Style.RESET_ALL}")
            
        print(f"{Fore.GREEN}Returning all {len(sorted_artists)} artists{Style.RESET_ALL}")
        return sorted_artists