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
    
    def scan(self) -> List[Tuple[str, int]]:
        """
        Scan the music library for FLAC files and extract artists.
        
        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        print(f"{Fore.CYAN}Scanning music library in {self.music_dir}...{Style.RESET_ALL}")
        artists = []
        processed_files = 0
        skipped_files = 0
        various_artists_albums = set()
        
        try:
            # First pass: identify Various Artists compilations
            for root, _, files in os.walk(self.music_dir):
                flac_files = [f for f in files if f.lower().endswith('.flac')]
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

            # Second pass: extract actual artists
            for root, _, files in os.walk(self.music_dir):
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