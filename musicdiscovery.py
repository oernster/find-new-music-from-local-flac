"""
Music Discovery module for finding new artists based on your FLAC library.
"""

import traceback
import argparse
import json
import time
import os
import sys
import random
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from colorama import Fore, Style, init
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

from libraryscanner import MusicLibraryScanner, ProgressTrackingFlacScanner
from musicbrainz import MusicBrainzAPI, normalize_artist_name


# Fix console encoding issues on Windows
if sys.platform == 'win32':
    # Force stdin/stdout to use UTF-8
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Initialize colorama
init(autoreset=True)

# Constants
DEFAULT_RECOMMENDATION_LIMIT = 50
DEFAULT_EMAIL = "your email"  # Default email for MusicBrainz API


class JsonFilePersistence:
    """Save recommendations to a JSON file."""
    
    def __init__(self, output_file: Optional[str] = None):
        """
        Initialize the JSON file persistence.
        
        Args:
            output_file (Optional[str]): Path to save recommendations to (None to skip saving)
        """
        self.output_file = output_file
    
    def save(self, recommendations: Dict[str, List[str]]) -> None:
        """
        Save recommendations to a JSON file.
        
        Args:
            recommendations (Dict[str, List[str]]): Dictionary of recommendations
        """
        if not self.output_file:
            return
            
        try:
            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(os.path.abspath(self.output_file)), exist_ok=True)
            
            # Filter out invalid source artists and their recommendations
            filtered_recommendations = {}
            for artist, recs in recommendations.items():
                # Skip if artist name is invalid or empty
                if not artist or should_exclude_artist(artist):
                    print(f"{Fore.YELLOW}Excluding invalid source artist: {artist}{Style.RESET_ALL}")
                    continue
                
                # Filter out invalid recommended artists
                valid_recs = [
                    rec for rec in recs 
                    if rec and not should_exclude_artist(rec)
                ]
                
                # Only add if there are valid recommendations
                if valid_recs:
                    filtered_recommendations[artist] = valid_recs
            
            # Save the filtered recommendations
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(filtered_recommendations, f, indent=2)
            
            print(f"\n{Fore.GREEN}Recommendations saved to {self.output_file}{Style.RESET_ALL}")
            
            # Print summary of saved recommendations
            total_source_artists = len(filtered_recommendations)
            total_recommendations = sum(len(recs) for recs in filtered_recommendations.values())
            print(f"{Fore.CYAN}Total source artists with recommendations: {total_source_artists}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Total recommended artists: {total_recommendations}{Style.RESET_ALL}")
            
        except Exception as e:
            print(f"{Fore.RED}Error saving recommendations: {e}{Style.RESET_ALL}")
            print(f"{Fore.RED}Traceback: {traceback.format_exc()}{Style.RESET_ALL}")
            

def create_comprehensive_library_exclusion_set(library_artists: Set[str]) -> Set[str]:
    """
    Create a comprehensive set of library artists with multiple variations.
    
    Args:
        library_artists (Set[str]): Original set of library artists
    
    Returns:
        Set[str]: Expanded set of library artists with multiple matching variations
    """
    comprehensive_set = set()
    
    for artist in library_artists:
        # Trim and normalize
        artist = artist.strip()
        if not artist:
            continue
        
        # Add normalized variation and a few other potential variations
        variations = [
            normalize_artist_name(artist),
            artist.lower(),
            artist.split('&')[0].strip(),  # Handle band names with '&'
            artist.split('feat.')[0].strip(),  # Handle featured artists
        ]
        
        # Remove duplicates and add to set
        comprehensive_set.update(set(variations))
    
    print(f"{Fore.CYAN}Total library exclusion variations: {len(comprehensive_set)}{Style.RESET_ALL}")
    if comprehensive_set:
        print(f"{Fore.YELLOW}Sample exclusion entries: {list(comprehensive_set)[:10]}{Style.RESET_ALL}")
    
    return comprehensive_set


def should_exclude_artist(artist_name: str) -> bool:
    """
    Check if an artist should be excluded from recommendations.
    
    Args:
        artist_name (str): Name of the artist to check
        
    Returns:
        bool: True if artist should be excluded, False otherwise
    """
    # Convert to lowercase for case-insensitive matching
    name_lower = artist_name.lower()
    
    # Exclude specific artist names
    exclude_names = [
        'unknown', '[unknown]', 'various artists', 'various', 'va', 'v.a.',
        'soundtrack', 'original soundtrack', 'ost', 'compilation'
    ]
    
    # Check for exact matches with exclusion list
    if any(name_lower == excluded for excluded in exclude_names):
        return True
    
    # Check for square brackets which often indicate metadata issues
    if '[' in name_lower and ']' in name_lower:
        return True
    
    # Check for unicode characters that might indicate encoding issues
    # This checks if more than 50% of characters are non-ASCII
    non_ascii_count = sum(1 for c in artist_name if ord(c) > 127)
    if len(artist_name) > 0 and non_ascii_count / len(artist_name) > 0.5:
        return True
        
    return False


class MusicRecommendationService:
    """Service for generating music recommendations based on library artists."""
    
    def __init__(self, music_db: MusicBrainzAPI, library_artists: Set[str]):
        """
        Initialize recommendation service with library artists to exclude.
        
        Args:
            music_db (MusicBrainzAPI): Music database API
            library_artists (Set[str]): Set of artists already in the library
        """
        self.music_db = music_db
        
        # Store both raw and normalized versions of library artists
        self.library_artists_raw = {
            str(artist).lower().strip() 
            for artist in library_artists 
            if artist and str(artist).strip()
        }
        
        # Store normalized versions for more robust matching
        self.library_artists_normalized = {
            normalize_artist_name(artist)
            for artist in library_artists
            if artist and str(artist).strip()
        }
        
        print(f"\n{Fore.CYAN}Total Library Artists: {len(self.library_artists_raw)}{Style.RESET_ALL}")
        if self.library_artists_raw:
            print(f"{Fore.YELLOW}First 20 Library Artists:{Style.RESET_ALL}")
            print(list(self.library_artists_raw)[:20])

    def is_library_artist(self, artist_name: str) -> bool:
        """
        Check if an artist is in the library using normalized matching.
        
        Args:
            artist_name (str): Name of the artist to check
            
        Returns:
            bool: True if artist is in library, False otherwise
        """
        if not artist_name:
            print(f"{Fore.YELLOW}Empty artist name received by is_library_artist().{Style.RESET_ALL}")
            return False

        cleaned_artist = str(artist_name).lower().strip()
        normalized_artist = normalize_artist_name(artist_name)
        
        # Check against both raw and normalized artist sets
        if cleaned_artist in self.library_artists_raw:
            print(f"{Fore.RED}Artist '{artist_name}' found in library (raw match).{Style.RESET_ALL}")
            return True
        if normalized_artist in self.library_artists_normalized:
            print(f"{Fore.RED}Artist '{artist_name}' found in library (normalized match: '{normalized_artist}').{Style.RESET_ALL}")
            return True
        
        return False

    def get_recommendations(self, source_artists: List[Tuple[str, int]], 
                  limit: int = 10) -> Dict[str, List[str]]:
        """
        Generate music recommendations based on artist genres.
        
        Args:
            source_artists (List[Tuple[str, int]]): List of (artist_name, count) tuples
            limit (int): Maximum number of recommendations per artist (default 10)
        
        Returns:
            Dict[str, List[str]]: Dictionary of recommendations
        """
        recommendations = {}
        all_recommended_artists = set()  # Global set to track all recommended artists

        # Define broader genre families
        genre_families = {
            'electronic': ['electronic', 'electronica', 'trance', 'house', 'techno', 'edm', 
                           'dubstep', 'drum and bass', 'ambient', 'idm', 'chillout', 
                           'electro', 'dance', 'synth', 'synth-pop'],
            
            'rock': ['rock', 'alternative rock', 'indie rock', 'hard rock', 'classic rock', 
                     'progressive rock', 'art rock', 'psychedelic rock', 'post-rock', 
                     'garage rock', 'grunge', 'punk rock', 'metal', 'heavy metal', 'post-punk'],
            
            'pop': ['pop', 'dance pop', 'synth pop', 'indie pop', 'pop rock', 'electropop', 
                    'dream pop', 'power pop', 'art pop', 'britpop', 'k-pop', 'j-pop'],
            
            'hip hop': ['hip hop', 'rap', 'trap', 'drill', 'grime', 'conscious rap', 'alternative hip hop'],
            
            'r&b': ['r&b', 'soul', 'neo-soul', 'contemporary r&b', 'funk'],
            
            'jazz': ['jazz', 'bebop', 'fusion', 'smooth jazz', 'jazz fusion', 
                     'contemporary jazz', 'acid jazz', 'free jazz', 'swing', 'big band'],
            
            'classical': ['classical', 'baroque', 'romantic', 'contemporary classical', 
                          'opera', 'chamber music', 'symphony', 'orchestral', 'piano'],
            
            'folk': ['folk', 'folk rock', 'indie folk', 'contemporary folk', 'traditional folk', 
                     'singer-songwriter', 'americana', 'bluegrass'],
            
            'world': ['world', 'reggae', 'latin', 'afrobeat', 'bossa nova', 'flamenco', 
                      'salsa', 'samba', 'traditional', 'celtic', 'worldbeat'],
        }

        print(f"\n{Fore.CYAN}Starting recommendation process for {len(source_artists)} source artists.{Style.RESET_ALL}")

        # Only keep valid artists based on exclusion rules
        valid_artists = [(artist, count) for artist, count in source_artists if not should_exclude_artist(artist)]
        print(f"{Fore.CYAN}Filtered {len(valid_artists)} valid artists for processing.{Style.RESET_ALL}")

        # Process all artists
        total_artists = len(valid_artists)
        
        for idx, (artist_name, _) in enumerate(valid_artists):
            try:
                # Calculate and print progress
                progress_percent = ((idx + 1) / total_artists) * 100
                print(f"Progress: {progress_percent:.1f}% ({idx + 1}/{total_artists} artists)")
                
                print(f"{Fore.WHITE}{Style.BRIGHT}=== PROCESSING: {artist_name} ==={Style.RESET_ALL}")
                
                # Search for the artist on MusicBrainz
                print(f"{Fore.MAGENTA}DEBUG: Searching for artist '{artist_name}' on MusicBrainz{Style.RESET_ALL}")
                artist_info = None
                try:
                    artist_info = self.music_db.search_artist(artist_name)
                    if not artist_info:
                        print(f"{Fore.YELLOW}Could not find MusicBrainz data for {artist_name}{Style.RESET_ALL}")
                        continue
                except Exception as e:
                    print(f"{Fore.RED}ERROR: MusicBrainz search failed: {str(e)}{Style.RESET_ALL}")
                    continue
                
                # Force 3-second delay before next request
                print(f"{Fore.YELLOW}Pausing for 2 seconds to avoid rate limiting...{Style.RESET_ALL}")
                time.sleep(2)
                
                # Get the artist's genres
                print(f"{Fore.MAGENTA}DEBUG: Requesting genres for artist ID: {artist_info.get('id', 'unknown')}{Style.RESET_ALL}")
                source_genres = []
                try:
                    source_genres = self.music_db.get_artist_genres(artist_info['id'])
                    print(f"{Fore.MAGENTA}DEBUG: Genre request successful{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}ERROR: Failed to get genres: {str(e)}{Style.RESET_ALL}")
                    source_genres = []
                
                # Skip if no genres found
                if not source_genres:
                    print(f"{Fore.YELLOW}No genres found for {artist_name}. Skipping.{Style.RESET_ALL}")
                    continue
                
                # Identify source artist's primary genre families
                source_genre_families = set()
                for genre in source_genres:
                    genre_lower = genre.lower()
                    for family_name, family_genres in genre_families.items():
                        if any(family_genre in genre_lower for family_genre in family_genres):
                            source_genre_families.add(family_name)
                
                # If no genre families match, skip this artist
                if not source_genre_families:
                    print(f"{Fore.YELLOW}No matching genre families for {artist_name}. Skipping.{Style.RESET_ALL}")
                    continue
                
                print(f"{Fore.CYAN}Source artist genres: {source_genres}{Style.RESET_ALL}")
                print(f"{Fore.CYAN}Source artist genre families: {list(source_genre_families)}{Style.RESET_ALL}")
                
                # Fetch a list of all artists
                try:
                    all_artists_candidates = self.music_db.fetch_artists_by_genres(
                        list(source_genre_families), 
                        limit=100  # Fetch more to allow for filtering
                    )
                except Exception as e:
                    print(f"{Fore.RED}ERROR: Failed to fetch artists by genre: {str(e)}{Style.RESET_ALL}")
                    continue
                
                # Filter candidates
                candidates = []
                for candidate_artist in all_artists_candidates:
                    recommended_name = candidate_artist.get('name', '').strip()
                    
                    # Skip empty or problematic names
                    if not recommended_name or should_exclude_artist(recommended_name):
                        continue
                    
                    # Skip if already in library or already recommended
                    normalized_name = normalize_artist_name(recommended_name)
                    if (self.is_library_artist(recommended_name) or 
                        normalized_name in all_recommended_artists):
                        continue
                    
                    # Optional: Ensure a minimum similarity to source genres
                    try:
                        candidate_genres = self.music_db.get_artist_genres(candidate_artist['id'])
                        
                        # Calculate genre overlap
                        genre_overlap = len(
                            set(g.lower() for g in source_genres) & 
                            set(g.lower() for g in candidate_genres)
                        )
                        
                        # Score based on genre overlap and coverage
                        genre_score = genre_overlap / len(source_genres) if source_genres else 0
                        
                        # If there's genre match, add to candidates
                        if genre_score > 0.3:  # At least 30% genre overlap
                            candidates.append((recommended_name, normalized_name, genre_score))
                    except Exception:
                        # If genre lookup fails, we'll skip this candidate
                        continue
                
                # Sort candidates by genre score
                candidates.sort(key=lambda x: x[2], reverse=True)
                
                # Take top recommendations
                filtered_recommendations = []
                for name, normalized_name, score in candidates[:limit]:
                    filtered_recommendations.append(name)
                    all_recommended_artists.add(normalized_name)
                    print(f"{Fore.MAGENTA}DEBUG: Adding '{name}' to final recommendations (score: {score:.2f}){Style.RESET_ALL}")
                
                # Store recommendations if found
                if filtered_recommendations:
                    recommendations[artist_name] = filtered_recommendations
                    print(f"{Fore.GREEN}Added {len(filtered_recommendations)} recommendations for '{artist_name}'.{Style.RESET_ALL}")
                    print(f"{Fore.GREEN}Recommendations: {filtered_recommendations}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}No valid recommendations found for '{artist_name}'.{Style.RESET_ALL}")
                    
            except Exception as e:
                print(f"{Fore.RED}Error processing '{artist_name}': {e}{Style.RESET_ALL}")
                import traceback
                traceback.print_exc()

        # Print final progress
        print(f"Progress: 100.0% ({total_artists}/{total_artists} artists)")
        
        print(f"\n{Fore.MAGENTA}{Style.BRIGHT}=== RECOMMENDATION SUMMARY ==={Style.RESET_ALL}")
        print(f"{Fore.CYAN}Total source artists with recommendations: {len(recommendations)}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Total unique recommended artists: {len(all_recommended_artists)}{Style.RESET_ALL}")
        
        # Print sample recommendations
        if recommendations:
            print(f"\n{Fore.GREEN}Sample recommendations:{Style.RESET_ALL}")
            for source, recs in list(recommendations.items())[:3]:
                print(f"{Fore.YELLOW}{source}: {Fore.BLUE}{recs}{Style.RESET_ALL}")
            
            if len(recommendations) > 3:
                print(f"{Fore.YELLOW}... and {len(recommendations) - 3} more source artists{Style.RESET_ALL}")
        
        # Final filter: Ensure no library artists are in the recommendations
        filtered_recommendations = {}
        for source_artist, recommended_artists in recommendations.items():
            # Filter out any library artists from recommendations
            filtered_artists = [
                artist for artist in recommended_artists 
                if not self.is_library_artist(artist)
            ]
            
            # Only add if we have recommendations after filtering
            if filtered_artists:
                filtered_recommendations[source_artist] = filtered_artists
        
        # Print the final filter results
        removed_artists = len(recommendations) - len(filtered_recommendations)
        if removed_artists > 0:
            print(f"{Fore.YELLOW}Removed {removed_artists} source artists that had no valid recommendations after filtering.{Style.RESET_ALL}")
        
        print(f"{Fore.GREEN}Final number of source artists with recommendations: {len(filtered_recommendations)}{Style.RESET_ALL}")
        
        return filtered_recommendations
    
class MusicDiscoveryApp:
    """Main application for music discovery."""
    
    def __init__(
        self, 
        scanner: MusicLibraryScanner,
        music_db: MusicBrainzAPI,
        persistence: JsonFilePersistence
    ):
        """
        Initialize the Music Discovery app.
        
        Args:
            scanner (MusicLibraryScanner): Library scanner
            music_db (MusicBrainzAPI): Music database API
            persistence (JsonFilePersistence): Output persistence
        """
        self.scanner = scanner
        self.music_db = music_db
        self.persistence = persistence

    def run(self, max_source_artists: Optional[int] = None) -> None:
        """
        Run the music discovery process with enhanced handling of Various Artists compilations.
        
        Args:
            max_source_artists (Optional[int]): Maximum number of source artists to process 
                                              (None for entire library)
        """
        # Phase 1: Scan the library to get artists
        print(f"{Fore.CYAN}Phase 1: Scanning music library{Style.RESET_ALL}")
        
        # Use the enhanced scan method if available
        if hasattr(self.scanner, 'scan_with_musicbrainz'):
            print(f"{Fore.GREEN}Using enhanced scanner with MusicBrainz integration{Style.RESET_ALL}")
            library_artists = self.scanner.scan_with_musicbrainz()
        else:
            # Fall back to standard scan method
            library_artists = self.scanner.scan()
        
        if max_source_artists is not None:
            library_artists = library_artists[:max_source_artists]
            
        # Filter out invalid artists during extraction
        library_artists = [
            (artist, count) for artist, count in library_artists 
            if not should_exclude_artist(artist)
        ]
        
        # Extract artist names from filtered library_artists
        library_artist_names = {artist for artist, _ in library_artists}
        
        # Phase 2: Generate recommendations
        print(f"{Fore.CYAN}Phase 2: Generating music recommendations{Style.RESET_ALL}")
        # Create recommendation service
        recommendation_service = MusicRecommendationService(
            music_db=self.music_db,
            library_artists=library_artist_names
        )
        
        # Get recommendations from library artists
        recommendations = recommendation_service.get_recommendations(
            library_artists
        )
        
        # Phase 2.5: Process compilation albums for additional recommendations
        # Add an explicit delimiter that's easier to find in logs
        print(f"{Fore.CYAN}###################################################{Style.RESET_ALL}")
        print(f"{Fore.CYAN}RESET_PROGRESS_BAR_NOW - VARIOUS_ARTISTS_PROCESSING{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Phase 2.5: Processing compilation albums for additional recommendations{Style.RESET_ALL}")
        print(f"Progress: 0% (0/0 compilation albums)")
        print(f"{Fore.CYAN}###################################################{Style.RESET_ALL}")
        
        # Use the new method to process compilations, passing library artist names
        updated_recommendations = self.process_compilations(recommendations, library_artist_names)
        
        # Update our recommendations with the new ones
        recommendations = updated_recommendations
        
        # Phase 3: Save recommendations
        print(f"{Fore.CYAN}Phase 3: Saving recommendations{Style.RESET_ALL}")
        self.persistence.save(recommendations)
        
        # Print summary
        print(f"\n{Fore.GREEN}=== RECOMMENDATION SUMMARY ==={Style.RESET_ALL}")
        print(f"{Fore.CYAN}Total recommendations: {len(recommendations)} artists{Style.RESET_ALL}")
        
    def process_compilations(self, existing_recommendations: Dict[str, List[str]], library_artist_names: Set[str]) -> Dict[str, List[str]]:
        """
        Process compilation albums to find all artists and generate recommendations.
        This supplements the main recommendations from the library scanner.
        
        Args:
            existing_recommendations (Dict[str, List[str]]): Existing recommendations
            library_artist_names (Set[str]): Set of artists already in the library
            
        Returns:
            Dict[str, List[str]]: Updated recommendations including compilation artists
        """
        print(f"{Fore.CYAN}Processing compilation albums for additional recommendations...{Style.RESET_ALL}")
        
        additional_recommendations = {}
        
        # Get compilation albums from the scanner if available
        compilation_albums = {}
        try:
            if hasattr(self.scanner, 'compilation_albums'):
                compilation_albums = self.scanner.compilation_albums
                print(f"{Fore.GREEN}Found {len(compilation_albums)} compilation albums in scanner data{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}Scanner does not have compilation_albums attribute. Using fallback method.{Style.RESET_ALL}")
                
                # Fallback: Search for albums with "Various Artists" in path
                for root, dirs, _ in os.walk(self.scanner.music_dir):
                    if "various artists" in root.lower():
                        for album_dir in dirs:
                            album_path = os.path.join(root, album_dir)
                            compilation_albums[album_dir] = set()
                            
                print(f"{Fore.GREEN}Found {len(compilation_albums)} compilation albums using fallback method{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error accessing compilation albums: {e}{Style.RESET_ALL}")
            return existing_recommendations
        
        # Skip if no compilation albums found
        if not compilation_albums:
            print(f"{Fore.YELLOW}No compilation albums found. Skipping.{Style.RESET_ALL}")
            return existing_recommendations
        
        # Create a set of artists already in the recommendations
        existing_artists = set(existing_recommendations.keys())
        
        # Copy the existing recommendations
        updated_recommendations = existing_recommendations.copy()
        
        # Create a set of normalized library artist names for quick lookup
        library_artists_normalized = {normalize_artist_name(artist) for artist in library_artist_names}
        
        # Setup and report progress tracking for compilation albums (specific format for ScriptWorker)
        total_albums = len(compilation_albums)
        albums_processed = 0
        
        # First print 0% progress with distinctive format
        print(f"Progress: 0% (0/{total_albums} compilation albums)")
        
        # Process each compilation album
        for album_name, album_artists in compilation_albums.items():
            # Update progress tracking for each album
            albums_processed += 1
            progress_percent = (albums_processed / total_albums) * 100
            
            # Use consistent format for progress reporting
            print(f"Progress: {progress_percent:.1f}% ({albums_processed}/{total_albums} compilation albums)")
            
            try:
                # Specific log format for album processing that will update the status text
                print(f"{Fore.CYAN}Processing compilation album: {album_name}{Style.RESET_ALL}")
                
                # Skip albums with no artists - we'll use MusicBrainz instead
                if not album_artists:
                    print(f"{Fore.YELLOW}No artists found for album '{album_name}'. Using MusicBrainz lookup.{Style.RESET_ALL}")
                    mb_artists = self.music_db.get_album_artists(album_name)
                    
                    # Use the MusicBrainz artists instead
                    album_artists = set(mb_artists)
                    print(f"{Fore.GREEN}Found {len(album_artists)} artists via MusicBrainz for '{album_name}'{Style.RESET_ALL}")
                
                # Process each artist from the compilation
                artist_count = len(album_artists)
                for i, artist in enumerate(album_artists, 1):
                    # Skip if already in existing recommendations
                    if artist in existing_artists:
                        print(f"{Fore.YELLOW}Artist '{artist}' already in recommendations. Skipping.{Style.RESET_ALL}")
                        continue
                    
                    # Skip if in library
                    normalized_artist = normalize_artist_name(artist)
                    if normalized_artist in library_artists_normalized:
                        print(f"{Fore.YELLOW}Artist '{artist}' found in library. Skipping.{Style.RESET_ALL}")
                        continue
                    
                    try:
                        # Search for the artist on MusicBrainz
                        artist_info = self.music_db.search_artist(artist)
                        
                        if not artist_info:
                            print(f"{Fore.YELLOW}Could not find MusicBrainz data for {artist}. Skipping.{Style.RESET_ALL}")
                            continue
                        
                        # Respect rate limits
                        time.sleep(2)
                        
                        # Get similar artists
                        similar_artists = self.music_db.get_similar_artists(
                            artist_info['id'],
                            limit=10  # Limit to 10 similar artists per compilation artist
                        )
                        
                        # Extract names only
                        similar_artist_names = [a.get('name', '') for a in similar_artists if a]
                        
                        # Filter out empty names and library artists
                        similar_artist_names = [
                            name for name in similar_artist_names 
                            if name and normalize_artist_name(name) not in library_artists_normalized
                        ]
                        
                        # Store recommendations if found
                        if similar_artist_names:
                            updated_recommendations[artist] = similar_artist_names
                            # Use a specific format that will be detected to update the status
                            print(f"{Fore.GREEN}Added {len(similar_artist_names)} recommendations for '{artist}' from compilation{Style.RESET_ALL}")
                        
                    except Exception as e:
                        print(f"{Fore.RED}Error processing artist '{artist}': {e}{Style.RESET_ALL}")
                    
                    # Respect rate limits
                    time.sleep(2)
            
            except Exception as e:
                print(f"{Fore.RED}Error processing album '{album_name}': {e}{Style.RESET_ALL}")
        
        # Print final progress - ensure it shows 100%
        print(f"Progress: 100.0% ({total_albums}/{total_albums} compilation albums)")
        
        # Print summary
        new_recommendations = len(updated_recommendations) - len(existing_recommendations)
        print(f"{Fore.GREEN}Processed {albums_processed} compilation albums{Style.RESET_ALL}")
        print(f"{Fore.GREEN}Added {new_recommendations} new artists with recommendations{Style.RESET_ALL}")
        
        return updated_recommendations
        
    def generate_recommendations_from_compilations(self, library_artists: List[Tuple[str, int]], various_artists_albums: Dict[str, str]) -> Dict[str, List[str]]:
        """
        Generate additional recommendations from compilation albums.
        
        Args:
            library_artists (List[Tuple[str, int]]): List of (artist_name, count) tuples from library
            various_artists_albums (Dict[str, str]): Dictionary mapping directory paths to album names
            
        Returns:
            Dict[str, List[str]]: Dictionary of additional recommendations
        """
        print(f"{Fore.CYAN}Generating recommendations from compilation albums...{Style.RESET_ALL}")
        
        additional_recommendations = {}
        
        # Skip if no compilation albums found
        if not various_artists_albums:
            print(f"{Fore.YELLOW}No compilation albums found. Skipping.{Style.RESET_ALL}")
            return {}
        
        # Initialize MusicBrainz API
        try:
            mb_api = self.music_db  # Reuse existing MusicBrainzAPI instance
        except AttributeError:
            print(f"{Fore.RED}MusicBrainz API not available. Skipping compilation recommendations.{Style.RESET_ALL}")
            return {}
        
        # Create a set of existing library artists for quick lookup
        library_artist_names = {artist.lower() for artist, _ in library_artists}
        
        # Cache for artists to avoid repeated API calls
        artist_cache = {}
        album_artists_cache = {}
        
        # Process each compilation album
        for album_path, album_name in various_artists_albums.items():
            print(f"{Fore.CYAN}Processing compilation album: {album_name}{Style.RESET_ALL}")
            
            # Get artists from the album
            if album_name in album_artists_cache:
                album_artists = album_artists_cache[album_name]
            else:
                album_artists = mb_api.get_album_artists(album_name)
                album_artists_cache[album_name] = album_artists
            
            if not album_artists:
                print(f"{Fore.YELLOW}No artists found for album '{album_name}'. Skipping.{Style.RESET_ALL}")
                continue
            
            # Find similar artists for each compilation artist
            for artist_name in album_artists:
                # Skip if artist is already in our library
                if artist_name.lower() in library_artist_names:
                    continue
                    
                # Skip if we've already processed this artist
                if artist_name in additional_recommendations:
                    continue
                    
                try:
                    # Search for the artist on MusicBrainz
                    if artist_name in artist_cache:
                        artist_info = artist_cache[artist_name]
                    else:
                        print(f"{Fore.MAGENTA}Searching for artist '{artist_name}' on MusicBrainz{Style.RESET_ALL}")
                        artist_info = mb_api.search_artist(artist_name)
                        artist_cache[artist_name] = artist_info
                    
                    if not artist_info:
                        print(f"{Fore.YELLOW}Could not find MusicBrainz data for {artist_name}. Skipping.{Style.RESET_ALL}")
                        continue
                    
                    # Force 2-second delay before next request to respect rate limits
                    time.sleep(2)
                    
                    # Get similar artists through MusicBrainz relationships
                    similar_artists = mb_api.get_similar_artists(
                        artist_info['id'], 
                        limit=10  # Limit to 10 similar artists per compilation artist
                    )
                    
                    # Extract names only
                    similar_artist_names = [a.get('name', '') for a in similar_artists if a]
                    
                    # Filter out empty names and artists already in our library
                    similar_artist_names = [
                        name for name in similar_artist_names 
                        if name and name.lower() not in library_artist_names
                    ]
                    
                    # Store recommendations if found
                    if similar_artist_names:
                        additional_recommendations[artist_name] = similar_artist_names
                        print(f"{Fore.GREEN}Found {len(similar_artist_names)} recommendations for '{artist_name}' from compilation album.{Style.RESET_ALL}")
                        
                except Exception as e:
                    print(f"{Fore.RED}Error processing compilation artist '{artist_name}': {e}{Style.RESET_ALL}")
        
        # Print summary
        print(f"{Fore.GREEN}Generated additional recommendations for {len(additional_recommendations)} compilation artists.{Style.RESET_ALL}")
        return additional_recommendations


def print_banner() -> None:
    """Print a colorful banner."""
    banner = f"""
║{Fore.YELLOW} GenreGenius Music Discovery App - Find New Artists{Fore.CYAN} ║
"""
    print(banner)
    

def browse_directory() -> Optional[str]:
    """
    Open a file browser dialog to select a directory.
    
    Returns:
        Optional[str]: Selected directory path or None if canceled
    """
    # Hide the main tkinter window
    root = tk.Tk()
    root.withdraw()
    
    # Open the file dialog
    directory = filedialog.askdirectory(
        title="Select your music directory",
        mustexist=True
    )
    
    # Destroy the tkinter instance
    root.destroy()
    
    return directory if directory else None


def find_flac_files(directory):
    """
    Find all FLAC files in a directory recursively.
    
    Args:
        directory (str): Path to search for FLAC files
        
    Returns:
        list: List of paths to FLAC files
    """
    flac_files = []
    
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.flac'):
                flac_path = os.path.join(root, file)
                flac_files.append(flac_path)
    
    return flac_files
    
def extract_artists_from_flac(flac_files):
    """
    Extract unique artists from FLAC metadata.
    
    Args:
        flac_files (list): List of paths to FLAC files
        
    Returns:
        set: Set of unique artist names
    """
    artists = set()
    valid_files = 0
    
    for file_path in flac_files:
        try:
            # Skip invalid files
            if os.path.getsize(file_path) < 128:
                continue
                
            # Read the FLAC file using mutagen
            from mutagen.flac import FLAC
            audio = FLAC(file_path)
            
            if 'artist' in audio:
                for artist in audio['artist']:
                    if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                        artists.add(artist)
            
            valid_files += 1
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    print(f"Found {len(artists)} unique artists in {valid_files} valid FLAC files.")
    return artists


def organize_artists_by_directory(flac_files):
    """
    Organize artists by directory for better structured processing.
    Uses the directory structure to correctly identify artists, not albums.
    
    Args:
        flac_files (list): List of paths to FLAC files
        
    Returns:
        dict: Dictionary mapping artist names to lists of file paths
    """
    artist_directories = {}
    
    # Track potential artist directories
    potential_artist_dirs = {}
    
    # First pass: Analyze directory structure to identify artist directories
    for file_path in flac_files:
        # Get file path components
        path_components = Path(file_path).parts
        
        # Need at least 3 components: drive/root, artist, album
        if len(path_components) >= 3:
            # Potential artist is usually 2 levels up from the file
            # Example: H:/music/Artist/Album/track.flac
            potential_artist = path_components[-3]  # Artist
            album_dir = path_components[-2]  # Album
            
            # Skip if either directory is "Various Artists"
            if (potential_artist.lower() in ('various artists', 'various', 'va', 'v.a.') or
                album_dir.lower() in ('various artists', 'various', 'va', 'v.a.')):
                continue
            
            # Track this potential artist directory and its albums
            if potential_artist not in potential_artist_dirs:
                potential_artist_dirs[potential_artist] = set()
            
            potential_artist_dirs[potential_artist].add(album_dir)
    
    # Second pass: Organize files by artist, now that we've identified valid artists
    for file_path in flac_files:
        path_components = Path(file_path).parts
        
        # Handle files at least 3 components deep
        if len(path_components) >= 3:
            potential_artist = path_components[-3]  # Artist
            
            # If this is a directory we've identified as an artist
            if potential_artist in potential_artist_dirs and len(potential_artist_dirs[potential_artist]) > 0:
                if potential_artist not in artist_directories:
                    artist_directories[potential_artist] = []
                
                artist_directories[potential_artist].append(file_path)
    
    return artist_directories
    

def process_music_library(music_dir, mb_email=DEFAULT_EMAIL):
    """
    Process the music library to find similar artists.
    
    Args:
        music_dir (str): Path to the music directory
        mb_email (str): Email to use for MusicBrainz API requests
        
    Returns:
        dict: Dictionary mapping source artists to lists of recommended artists
    """
    # Initialize MusicBrainz API with the provided email
    mb_api = MusicBrainzAPI(user_email=mb_email)
    
    # Find all FLAC files in the directory
    flac_files = find_flac_files(music_dir)
    
    if not flac_files:
        print(f"No FLAC files found in {music_dir}. Please check the directory.")
        return {}
    
    print(f"Found {len(flac_files)} FLAC files to analyze.")
    
    # Extract unique artists from FLAC metadata
    metadata_artists = extract_artists_from_flac(flac_files)
    
    if not metadata_artists:
        print("No artists found in FLAC metadata.")
        return {}
    
    print(f"Found {len(metadata_artists)} unique artists in FLAC metadata.")
    
    # Get recommendations for each artist
    recommendations = {}
    
    # First pass - group artists by directory structure
    # This will identify artists based on directory structure, not just immediate parent dir
    artist_directories = organize_artists_by_directory(flac_files)
    
    # Print the identified artists from directory structure
    directory_artists = set(artist_directories.keys())
    print(f"Identified {len(directory_artists)} artists from directory structure.")
    if directory_artists:
        print(f"Sample artists from directory structure: {list(directory_artists)[:5]}")
    
    # Process artists by directory structure first
    total_artists = len(directory_artists)
    processed_artists = 0
    
    for artist_name, file_list in artist_directories.items():
        processed_artists += 1
        percentage = (processed_artists / total_artists) * 100 if total_artists > 0 else 100
        
        # Progress indicator for first cycle
        print(f"Progress: {percentage:.1f}% ({processed_artists}/{total_artists} artists)")
        
        print(f"=== PROCESSING: {artist_name} ===")
        try:
            # Get similar artists from MusicBrainz
            print(f"Searching MusicBrainz for artist: {artist_name}")
            artist_data = mb_api.search_artist(artist_name)
            
            if artist_data:
                print(f"Found artist in MusicBrainz: {artist_data.get('name', 'Unknown')}")
                
                # Get similar artists
                similar_artists = mb_api.get_similar_artists(artist_data['id'], limit=10)
                
                # Extract names from similar artists data
                similar_names = [a.get('name', '') for a in similar_artists if a]
                
                # Filter out empty names and duplicates while preserving order
                similar_names = [name for name in similar_names if name and name != artist_name]
                
                # Add to recommendations
                if similar_names:
                    recommendations[artist_name] = similar_names
                    print(f"Found {len(similar_names)} similar artists for {artist_name}")
                else:
                    print(f"No similar artists found for {artist_name}")
            else:
                print(f"Artist not found in MusicBrainz: {artist_name}")
        
        except Exception as e:
            print(f"Error processing artist {artist_name}: {e}")
            
        # Add a small delay to respect API rate limits
        time.sleep(1.0)
    
    print(f"Finished processing {total_artists} artists from directory structure")
    
    # Get additional artists from metadata that weren't found in directory structure
    metadata_only_artists = metadata_artists - directory_artists
    
    if metadata_only_artists:
        print(f"\nProcessing {len(metadata_only_artists)} additional artists found in metadata...")
        
        metadata_total = len(metadata_only_artists)
        for idx, artist_name in enumerate(metadata_only_artists):
            metadata_processed = idx + 1
            metadata_percentage = (metadata_processed / metadata_total) * 100
            
            # Progress indicator for second cycle - use the SAME format as first cycle
            print(f"Progress: {metadata_percentage:.1f}% ({metadata_processed}/{metadata_total} artists)")
            
            print(f"=== PROCESSING: {artist_name} ===")
            try:
                # Get similar artists from MusicBrainz
                print(f"Searching MusicBrainz for artist: {artist_name}")
                artist_data = mb_api.search_artist(artist_name)
                
                if artist_data:
                    print(f"Found artist in MusicBrainz: {artist_data.get('name', 'Unknown')}")
                    
                    # Get similar artists
                    similar_artists = mb_api.get_similar_artists(artist_data['id'], limit=10)
                    
                    # Extract names from similar artists data
                    similar_names = [a.get('name', '') for a in similar_artists if a]
                    
                    # Filter out empty names and duplicates while preserving order
                    similar_names = [name for name in similar_names if name and name != artist_name]
                    
                    # Add to recommendations
                    if similar_names:
                        recommendations[artist_name] = similar_names
                        print(f"Found {len(similar_names)} similar artists for {artist_name}")
                    else:
                        print(f"No similar artists found for {artist_name}")
                else:
                    print(f"Artist not found in MusicBrainz: {artist_name}")
            
            except Exception as e:
                print(f"Error processing artist {artist_name}: {e}")
                
            # Add a small delay to respect API rate limits
            time.sleep(1.0)
    
    # Return the recommendations dictionary
    return recommendations


def main():
    """Main entry point for the Music Discovery script."""
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Music Discovery script to find similar artists in FLAC collection")
    parser.add_argument('--dir', dest='music_dir', help='Path to FLAC music directory')
    parser.add_argument('--save-in-music-dir', action='store_true', help='Save recommendations.json in music directory')
    parser.add_argument('--email', dest='mb_email', default=DEFAULT_EMAIL, 
                      help=f'Email to use for MusicBrainz API requests (default: {DEFAULT_EMAIL})')
    
    args = parser.parse_args()
    
    # Get music directory from command line or prompt user
    music_dir = args.music_dir
    if not music_dir:
        music_dir = select_directory()
        if not music_dir:
            print("No directory selected. Exiting.")
            return
    
    # Print banner and info
    print_banner()
    print(f"Using MusicBrainz email: {args.mb_email}")
    print(f"Scanning music library in {music_dir}...")
    
    # Process the library and generate recommendations
    try:
        start_time = time.time()
        recommendations = process_music_library(music_dir, mb_email=args.mb_email)
        process_time = time.time() - start_time
        print(f"Music discovery completed in {process_time:.2f} seconds")
        
        # Save recommendations
        if args.save_in_music_dir:
            output_file = os.path.join(music_dir, "recommendations.json")
        else:
            output_file = "recommendations.json"
        
        print(f"Saving recommendations to {output_file}")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(recommendations, f, indent=2)
        
        # Print summary
        total_source_artists = len(recommendations)
        total_recommendations = sum(len(similar_artists) for similar_artists in recommendations.values())
        print(f"\nTotal source artists with recommendations: {total_source_artists}")
        print(f"Total recommended artists: {total_recommendations}")
        print(f"Average recommendations per artist: {total_recommendations / total_source_artists:.1f}")
        print("\nMusic discovery complete!")
        
    except Exception as e:
        print(f"Error during music discovery: {e}")
        traceback.print_exc()
        return 1
    
    return 0
        

if __name__ == '__main__':
    main()