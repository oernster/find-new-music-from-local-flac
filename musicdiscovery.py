"""
Music Discovery module for finding new artists based on your FLAC library.
"""

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
DEFAULT_EMAIL = "oliverjernster@hotmail.com"  # Default email for MusicBrainz API


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
            
            # Ensure no duplicate recommendations exist before saving
            deduplicated_recommendations = {}
            
            for artist, similar_artists in recommendations.items():
                # Convert to a dict and back to a list to remove any duplicates
                unique_artists = list(dict.fromkeys(similar_artists))
                deduplicated_recommendations[artist] = unique_artists
            
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(deduplicated_recommendations, f, indent=2)
            print(f"\n{Fore.GREEN}Recommendations saved to {self.output_file}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error saving recommendations: {e}{Style.RESET_ALL}")


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
        
        return recommendations
    
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
        Run the music discovery process.
        
        Args:
            max_source_artists (Optional[int]): Maximum number of source artists to process 
                                              (None for entire library)
        """
        # Phase 1: Scan the library to get artists
        print(f"{Fore.CYAN}Phase 1: Scanning FLAC music library{Style.RESET_ALL}")
        library_artists = self.scanner.scan()
        
        if max_source_artists is not None:
            library_artists = library_artists[:max_source_artists]
            
        # Extract artist names from library_artists
        library_artist_names = {artist for artist, _ in library_artists}
        
        # Phase 2: Generate recommendations
        print(f"{Fore.CYAN}Phase 2: Generating music recommendations{Style.RESET_ALL}")
        # Create recommendation service
        recommendation_service = MusicRecommendationService(
            music_db=self.music_db,
            library_artists=library_artist_names
        )
        
        # Get recommendations
        recommendations = recommendation_service.get_recommendations(
            library_artists
        )
        
        # Phase 3: Save recommendations
        print(f"{Fore.CYAN}Phase 3: Saving recommendations{Style.RESET_ALL}")
        self.persistence.save(recommendations)
        
        # Print summary
        print(f"\n{Fore.GREEN}=== RECOMMENDATION SUMMARY ==={Style.RESET_ALL}")
        print(f"{Fore.CYAN}Total recommendations: {len(recommendations)} artists{Style.RESET_ALL}")


def print_banner() -> None:
    """Print a colorful banner."""
    banner = f"""
{Fore.CYAN}{Style.BRIGHT}╔═══════════════════════════════════════════════╗
║  {Fore.YELLOW}FLAC Music Discovery App {Fore.WHITE}- Find New Artists  {Fore.CYAN}║
╚═══════════════════════════════════════════════╝{Style.RESET_ALL}
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
        title="Select your FLAC music directory",
        mustexist=True
    )
    
    # Destroy the tkinter instance
    root.destroy()
    
    return directory if directory else None


def main():
    """Main entry point for the application."""
    print_banner()
    
    # Parse arguments
    parser = argparse.ArgumentParser(description='Discover new music')
    parser.add_argument('--dir', type=str, help='Directory with music files')
    parser.add_argument('--output', type=str, default='./recommendations.json')
    parser.add_argument('--email', type=str, default=DEFAULT_EMAIL)
    parser.add_argument('--max-artists', type=int, default=None, 
                       help='Maximum number of artists to process (leave empty for entire library)')
    parser.add_argument('--save-in-music-dir', action='store_true', 
                       help='Save recommendations.json in the music directory')

    args = parser.parse_args()
    
    # Use the directory from command-line args, or open browser if not specified
    music_dir = args.dir
    if not music_dir:
        print(f"{Fore.YELLOW}No directory specified, opening directory browser...{Style.RESET_ALL}")
        music_dir = browse_directory()
        if not music_dir:
            print(f"{Fore.RED}No directory selected. Exiting.{Style.RESET_ALL}")
            return
    
    # Validate the directory exists
    if not os.path.isdir(music_dir):
        print(f"{Fore.RED}Error: Directory {music_dir} does not exist.{Style.RESET_ALL}")
        return
        
    print(f"{Fore.GREEN}Using music directory: {music_dir}{Style.RESET_ALL}")
    
    # Determine output file path based on save-in-music-dir flag
    if args.save_in_music_dir:
        output_file = os.path.join(music_dir, 'recommendations.json')
        print(f"{Fore.CYAN}Will save recommendations to music directory: {output_file}{Style.RESET_ALL}")
    else:
        output_file = args.output
        print(f"{Fore.CYAN}Will save recommendations to: {output_file}{Style.RESET_ALL}")
    
    # Create components
    scanner = ProgressTrackingFlacScanner(music_dir)  # Use the enhanced scanner
    music_db = MusicBrainzAPI(user_email=args.email)
    persistence = JsonFilePersistence(output_file=output_file)
    
    # Create and run app
    app = MusicDiscoveryApp(
        scanner=scanner,
        music_db=music_db,
        persistence=persistence
    )
    
    try:
        app.run(args.max_artists)
        print(f"\nMusic discovery complete! Check {output_file}")
    except Exception as e:
        print(f"Error during execution: {e}")
        import traceback
        traceback.print_exc()
        

if __name__ == '__main__':
    main()