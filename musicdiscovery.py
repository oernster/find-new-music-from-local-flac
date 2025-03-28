import argparse
import json
import time
import re
import os
import random
import tkinter as tk
from tkinter import filedialog
import requests
from colorama import init, Fore, Back, Style
from typing import Dict, List, Optional, Any, Set, Tuple, Callable
from abc import ABC, abstractmethod
from musicbrainz import MusicBrainzAPI, MusicDatabase, normalize_artist_name
from libraryscanner import MusicLibraryScanner, FlacLibraryScanner


# Initialize colorama
init(autoreset=True)

## Constants
BASE_REQUEST_DELAY = 4  # seconds between API requests
DEFAULT_RECOMMENDATION_LIMIT = 50  # Increased to get more recommendations
DEFAULT_EMAIL = "oliverjernster@hotmail.com"  # default email for MusicBrainz API


def create_comprehensive_library_exclusion_set(library_artists: Set[str]) -> Set[str]:
    """
    Create a comprehensive set of library artists with multiple variations.
    
    Args:
        library_artists: Original set of library artists
    
    Returns:
        Expanded set of library artists with multiple matching variations
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
    print(f"{Fore.YELLOW}Sample exclusion entries: {list(comprehensive_set)[:10]}{Style.RESET_ALL}")
    
    return comprehensive_set


def filter_library_artists(recommendations: Dict[str, List[str]], library_artists: Set[str]) -> Dict[str, List[str]]:
    """
    Filter out library artists from recommendations with more lenient matching.
    
    Args:
        recommendations: Dictionary of source artists to recommended artists
        library_artists: Set of library artists to exclude
    
    Returns:
        Filtered recommendations with library artists removed
    """
    filtered_recommendations = {}
    
    for source_artist, recommended_artists in recommendations.items():
        # Filter out library artists from recommendations
        filtered_recs = [
            rec for rec in recommended_artists 
            if not is_artist_in_library(rec, library_artists)
        ]
        
        if filtered_recs:
            filtered_recommendations[source_artist] = filtered_recs
    
    return filtered_recommendations


def should_exclude_artist(artist_name: str) -> bool:
    """
    Check if an artist should be excluded from recommendations.
    
    Args:
        artist_name: Name of the artist to check
        
    Returns:
        True if artist should be excluded, False otherwise
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


def is_library_artist(self, artist_name: str) -> bool:
    """
    Check if an artist is in the library using normalized matching.
    
    Args:
        artist_name: Name of the artist to check
        
    Returns:
        True if artist is in library, False otherwise
    """
    if not artist_name:
        return False

    # Normalize the input artist name
    normalized_artist = normalize_artist_name(artist_name)

    # Check if normalized name is in the normalized artist set
    return normalized_artist in self.library_artists_normalized



class JsonFilePersistence:
    """Save recommendations to a JSON file."""
    
    def __init__(self, output_file: Optional[str] = None):
        """
        Initialize the JSON file persistence.
        
        Args:
            output_file: Path to save recommendations to (None to skip saving)
        """
        self.output_file = output_file
    
    def save(self, recommendations: Dict) -> None:
        """Save recommendations to a JSON file."""
        if not self.output_file:
            return
            
        try:
            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(os.path.abspath(self.output_file)), exist_ok=True)
            
            # Ensure no duplicate recommendations exist before saving
            deduplicated_recommendations = {}
            
            for artist, similar_artists in recommendations.items():
                # Convert to a set and back to a list to remove any duplicates
                unique_artists = list(dict.fromkeys(similar_artists))
                deduplicated_recommendations[artist] = unique_artists
            
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(deduplicated_recommendations, f, indent=2)
            print(f"\n{Fore.GREEN}Recommendations saved to {self.output_file}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error saving recommendations: {e}{Style.RESET_ALL}")


class SimpleMusicRecommendationService:
    def __init__(self, music_db: MusicDatabase, library_artists: Set[str]):
        """
        Initialize recommendation service with library artists to exclude.
        
        Args:
            music_db: Music database API
            library_artists: Set of artists already in the library
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
        print(f"{Fore.YELLOW}First 20 Library Artists:{Style.RESET_ALL}")
        print(list(self.library_artists_raw)[:20])

    def is_library_artist(self, artist_name: str) -> bool:
        """
        Check if an artist is in the library using normalized matching with extensive logging.
        
        Args:
            artist_name: Name of the artist to check
            
        Returns:
            True if artist is in library, False otherwise
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


    def get_recommendations(self, source_artists: List[tuple], limit: int = 10) -> Dict[str, List[str]]:
        """
        Generate music recommendations with extensive logging.
        
        Args:
            source_artists: List of (artist_name, count) tuples
            limit: Maximum number of recommendations per artist (default 10)
        
        Returns:
            Dictionary of recommendations
        """
        recommendations = {}
        global_recommended_artists = set()

        print(f"\n{Fore.CYAN}Starting recommendation process for {len(source_artists)} source artists.{Style.RESET_ALL}")

        # Only keep valid artists based on exclusion rules
        valid_artists = [(artist, count) for artist, count in source_artists if not should_exclude_artist(artist)]
        print(f"{Fore.CYAN}Filtered {len(valid_artists)} valid artists for processing.{Style.RESET_ALL}")

        random.shuffle(valid_artists)

        for artist_name, _ in valid_artists:
            try:
                start_time = time.time()
                
                print(f"\n{Fore.WHITE}{Back.BLUE}=== PROCESSING: {artist_name} ==={Style.RESET_ALL}")
                
                artist_info = self.music_db.search_artist(artist_name)
                if not artist_info:
                    print(f"{Fore.RED}FAILED: No MusicBrainz data found for '{artist_name}'. Skipping.{Style.RESET_ALL}")
                    continue
                
                print(f"{Fore.GREEN}FOUND: MusicBrainz ID: {artist_info.get('id', 'N/A')}{Style.RESET_ALL}")
                
                similar_artists = self.music_db.get_similar_artists(
                    artist_id=artist_info['id'], 
                    limit=100
                )
                
                print(f"{Fore.CYAN}Retrieved {len(similar_artists)} similar artists from MusicBrainz.{Style.RESET_ALL}")
                
                filtered_recommendations = []
                used_normalized_names = set()

                for artist in similar_artists:
                    recommended_name = artist.get('name', '').strip()
                    
                    if not recommended_name:
                        print(f"{Fore.YELLOW}Encountered artist with an empty name. Skipping.{Style.RESET_ALL}")
                        continue

                    normalized_name = normalize_artist_name(recommended_name)
                    
                    # Check if artist should be filtered
                    in_global_set = normalized_name in global_recommended_artists
                    in_library = self.is_library_artist(recommended_name)
                    should_exclude = should_exclude_artist(recommended_name)
                    already_used = normalized_name in used_normalized_names
                    
                    print(f"\n{Fore.CYAN}Evaluating: '{recommended_name}'{Style.RESET_ALL}")
                    print(f"  Normalized: '{normalized_name}'")
                    print(f"  Already Used: {already_used}")
                    print(f"  Already Recommended Globally: {in_global_set}")
                    print(f"  In Library: {in_library}")
                    print(f"  Excluded: {should_exclude}")
                    
                    if already_used or in_global_set or in_library or should_exclude:
                        print(f"  {Fore.RED}FILTERED: Not adding to recommendations{Style.RESET_ALL}")
                        continue
                    
                    print(f"  {Fore.GREEN}ACCEPTED: Adding to recommendations{Style.RESET_ALL}")
                    filtered_recommendations.append(recommended_name)
                    used_normalized_names.add(normalized_name)
                    global_recommended_artists.add(normalized_name)
                    
                    if len(filtered_recommendations) >= limit:
                        break

                if filtered_recommendations:
                    recommendations[artist_name] = filtered_recommendations[:limit]
                    print(f"{Fore.GREEN}Added {len(filtered_recommendations)} recommendations for '{artist_name}'.{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}No valid recommendations found for '{artist_name}'.{Style.RESET_ALL}")

                end_time = time.time()
                print(f"{Fore.CYAN}Finished processing '{artist_name}' in {end_time - start_time:.2f} seconds.{Style.RESET_ALL}")
                
                # Pause between API requests to avoid rate limiting
                print(f"{Fore.YELLOW}Pausing for 6 seconds to avoid rate limiting...{Style.RESET_ALL}")
                time.sleep(6)
                
            except Exception as e:
                print(f"{Fore.RED}Error processing '{artist_name}': {e}{Style.RESET_ALL}")
                import traceback
                traceback.print_exc()

        print(f"\n{Fore.MAGENTA}{Back.WHITE}=== RECOMMENDATION SUMMARY ==={Style.RESET_ALL}")
        print(f"{Fore.CYAN}Total unique recommended artists: {len(global_recommended_artists)}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Total source artists with recommendations: {len(recommendations)}{Style.RESET_ALL}")
        
        # Print sample recommendations
        if recommendations:
            print(f"\n{Fore.GREEN}Sample recommendations:{Style.RESET_ALL}")
            for i, (source, recs) in enumerate(list(recommendations.items())[:3]):
                print(f"{Fore.YELLOW}{source}: {Fore.BLUE}{recs}{Style.RESET_ALL}")
                
            if len(recommendations) > 3:
                print(f"{Fore.YELLOW}... and {len(recommendations) - 3} more source artists{Style.RESET_ALL}")
        
        return recommendations

       
class MusicDiscoveryApp:
    def __init__(
        self, 
        scanner: MusicLibraryScanner,
        music_db: MusicDatabase,
        persistence: JsonFilePersistence
    ):
        """
        Initialize the Music Discovery app with a simplified approach.
        
        Args:
            scanner: Library scanner
            music_db: Music database API
            persistence: Output persistence
        """
        self.scanner = scanner
        self.music_db = music_db
        self.persistence = persistence

    def run(self, max_source_artists: Optional[int] = None):
        """
        Run the music discovery process.
        
        Args:
            max_source_artists: Maximum number of source artists to process (None for entire library)
        """
        # Scan the library to get artists
        library_artists = self.scanner.scan()
        
        if max_source_artists is not None:
            library_artists = library_artists[:max_source_artists]
            
        # Extract artist names from library_artists
        library_artist_names = {artist for artist, _ in library_artists}
        
        # Create recommendation service
        recommendation_service = SimpleMusicRecommendationService(
            music_db=self.music_db,
            library_artists=library_artist_names
        )
        
        # Get recommendations
        recommendations = recommendation_service.get_recommendations(
            library_artists
        )
        
        # Save recommendations
        self.persistence.save(recommendations)
        
        # Print summary
        print(f"\n=== RECOMMENDATION SUMMARY ===")
        print(f"Total recommendations: {len(recommendations)} artists")
        for source, recs in recommendations.items():
            print(f"{source}: {recs}")

                    
def browse_directory() -> Optional[str]:
    """
    Open a file browser dialog to select a directory.
    
    Returns:
        Selected directory path or None if canceled
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


def print_banner() -> None:
    """Print a colorful banner."""
    banner = f"""
{Fore.CYAN}{Style.BRIGHT}╔═══════════════════════════════════════════════╗
║  {Fore.YELLOW}FLAC Music Discovery App {Fore.WHITE}- Find New Artists  {Fore.CYAN}║
╚═══════════════════════════════════════════════╝{Style.RESET_ALL}
"""
    print(banner)


def main():
    print_banner()
    
    # Parse arguments
    parser = argparse.ArgumentParser(description='Discover new music')
    parser.add_argument('--dir', type=str, help='Directory with music files')
    parser.add_argument('--output', type=str, default='./recommendations.json')
    parser.add_argument('--email', type=str, default=DEFAULT_EMAIL)
    parser.add_argument('--max-artists', type=int, default=None, help='Maximum number of artists to process (leave empty for entire library)')

    args = parser.parse_args()
    
    # Get music directory
    music_dir = args.dir or browse_directory()
    if not music_dir:
        print("No directory selected. Exiting.")
        return
    
    # Create components
    scanner = FlacLibraryScanner(music_dir)
    music_db = MusicBrainzAPI(user_email=args.email)
    persistence = JsonFilePersistence(output_file=args.output)
    
    # Create and run app
    app = MusicDiscoveryApp(
        scanner=scanner,
        music_db=music_db,
        persistence=persistence
    )
    
    try:
        app.run()
        print(f"\nMusic discovery complete! Check {args.output}")
    except Exception as e:
        print(f"Error during execution: {e}")


if __name__ == '__main__':
    main()