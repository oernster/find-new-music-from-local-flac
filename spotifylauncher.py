"""
Spotify Launcher - GUI Application for Music Discovery and Spotify Playlist Creation.
"""

import sys
import os
import argparse
import subprocess
import webbrowser
import time
import threading
import traceback
import queue
import re
import json
from typing import List, Optional, Dict
import ctypes
from ctypes import windll, byref, sizeof, c_int

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QDialog, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QLineEdit,
    QTextEdit, QMenuBar, QMenu, QAction, QMessageBox, QProgressBar, QTabWidget, QWIDGETSIZE_MAX, QPushButton,
    QFileDialog, QCheckBox, QGroupBox
)
from PyQt5.QtGui import QIcon, QFont, QColor, QPalette, QPainter, QPainterPath
from PyQt5.QtCore import ( 
    Qt, QThread, pyqtSignal, QObject, QMutex, QMutexLocker, pyqtSlot, QEvent, QRect,
    QPropertyAnimation, QEasingCurve, pyqtProperty, QSize, QPointF, QRectF
)

DEFAULT_EMAIL = "oliverjernster@hotmail.com"  # Use the same email as in musicdiscovery.py

# Global dictionary to track last update times for different phases
STATUS_UPDATE_THROTTLE: Dict[str, float] = {
    'discovery': 0,
    'spotify_phase1': 0,
    'spotify_phase2': 0
}


# Thread-safe logger class to handle log operations safely
class ThreadSafeLogger(QObject):
    """Thread-safe logging mechanism to prevent UI crashes during log updates."""
    
    def __init__(self):
        """Initialize the thread-safe logger."""
        super().__init__()
        self.mutex = QMutex()
    
    def log_discovery(self, message, text_edit, status_label=None):
        """
        Thread-safe logging for discovery output.
        
        Args:
            message (str): Message to log
            text_edit (QTextEdit): Text edit widget to update
            status_label (QLabel, optional): Status label to update
        """
        with QMutexLocker(self.mutex):
            # Queue this operation to the main thread
            QApplication.instance().postEvent(
                self,
                LogEvent(lambda: self._update_log(text_edit, message, status_label))
            )
            # Also print to console as a backup
            print(f"DISCOVERY: {message}")
    
    def log_spotify(self, message, text_edit, status_label=None):
        """
        Thread-safe logging for spotify output.
        
        Args:
            message (str): Message to log
            text_edit (QTextEdit): Text edit widget to update
            status_label (QLabel, optional): Status label to update
        """
        with QMutexLocker(self.mutex):
            # Queue this operation to the main thread
            QApplication.instance().postEvent(
                self,
                LogEvent(lambda: self._update_log(text_edit, message, status_label))
            )
            # Also print to console as a backup
            print(f"SPOTIFY: {message}")
    
    def log_debug(self, message, text_edit):
        """
        Thread-safe logging for debug output.
        
        Args:
            message (str): Message to log
            text_edit (QTextEdit): Text edit widget to update
        """
        with QMutexLocker(self.mutex):
            # Queue this operation to the main thread
            QApplication.instance().postEvent(
                self,
                LogEvent(lambda: self._update_log(text_edit, message))
            )
            # Always print to console
            print(f"DEBUG: {message}")
    
    def _update_log(self, text_edit, message, status_label=None):
        """
        Update log text edit with the message.
        
        Args:
            text_edit (QTextEdit): Text edit widget to update
            message (str): Message to log
            status_label (QLabel, optional): Status label to update
        """
        try:
            if text_edit and not text_edit.isHidden():
                # Add timestamp
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                formatted_message = f"[{timestamp}] {message}"
                
                # Append message directly
                text_edit.append(formatted_message)
                
                # Ensure latest message is visible
                text_edit.ensureCursorVisible()
                
                # Update status label if provided and has truncate_status method
                if status_label and hasattr(self.parent(), 'truncate_status'):
                    truncated = self.parent().truncate_status(message)
                    status_label.setText(truncated)
        except Exception as e:
            # Print any errors to console
            print(f"Error in _update_log: {e} - Message was: {message}")


# Custom event for handling logging operations
class LogEvent(QEvent):
    """Custom event for logging operations to be processed in the main thread."""
    
    # Define a custom event type
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())
    
    def __init__(self, callback):
        """
        Initialize the log event.
        
        Args:
            callback (callable): Function to call when processing the event
        """
        super().__init__(self.EVENT_TYPE)
        self.callback = callback


class ColourProgressBar(QProgressBar):
    """Progress bar with color transitions based on progress percentage."""
    
    def __init__(self, parent=None):
        """Initialize the colored progress bar."""
        super().__init__(parent)
        self.setMinimumHeight(25)
        # Initialize with empty/gray styling
        self.setStyleSheet("""
            QProgressBar {
                border: 1px solid grey;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                color: black;
                height: 25px;
                background-color: #f0f0f0;
            }

            QProgressBar::chunk {
                background-color: #e0e0e0;
                width: 10px;
                margin: 0.5px;
            }
        """)
        self.setValue(0)  # Explicitly set initial value
        
    def updateStyleSheet(self, value):
        """
        Update the progress bar stylesheet to show individual colored chunks
        based on their position in the progress bar. Each chunk gets the color
        corresponding to its position in the overall progress range.
        
        Args:
            value (int): Progress value (0-100)
        """
        progress_bg = "#282828"        # Dark background
        border_color = "#333333"       # Border color
        
        # Define colors for each 10% segment
        colors = [
            "#8B2E2E",    # Deep red (0-10%)
            "#AB4F2C",    # Dark reddish-orange (10-20%)
            "#C16E2A",    # Reddish-orange (20-30%)
            "#D98D28",    # Burnt orange (30-40%)
            "#E6A426",    # Dark yellow-orange (40-50%)
            "#EDBA24",    # Yellow-orange (50-60%)
            "#C4D122",    # Olive yellow (60-70%)
            "#8AC425",    # Yellow-green (70-80%)
            "#45B927",    # Bright green (80-90%)
            "#1DB954"     # Spotify green (90-100%)
        ]
        
        # Get current color index based on progress
        color_index = min(int(value / 10), 9)
        
        # Set the color for new chunks (most recent in progress)
        current_color = colors[color_index]
        
        # Set alternating color pattern to create visual separation between chunks
        # This creates a slightly varied pattern for the chunks
        self.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {border_color};
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                color: white;
                height: 25px;
                background-color: {progress_bg};
            }}
            
            QProgressBar::chunk {{
                background-color: {current_color};
                width: 5px;
                margin: 0.5px;
                border-radius: 2px;
            }}
        """)
        
    def setValue(self, value):
        """
        Override setValue to update the color.
        
        Args:
            value (int): Progress value
        """
        # Make sure we're getting integer values
        if isinstance(value, float):
            value = int(value)
        
        # Force a repaint at the correct value
        self.updateStyleSheet(value)
        
        # Call the parent implementation to update the actual value
        super().setValue(value)
        
        # Force an update to ensure the UI reflects the change
        self.update()


# Add this class to your spotifylauncher.py file, before the SpotifyLauncher class

class ToggleSwitch(QCheckBox):
    """Custom toggle switch control that looks like a modern switch."""
    
    def __init__(self, parent=None):
        """Initialize the toggle switch."""
        super().__init__(parent)
        
        # Set dimensions and style
        self.setFixedSize(52, 26)
        
        # Remove text
        self.setText("")
        
        # Set animation details
        self.animation_duration = 120
        self.animation = None
        
        # Track state for custom drawing
        self._enabled = False
        self._margin = 2
        self._thumb_position = 0  # 0 for off, 1 for on (will be animated)
        
        # Colors
        self.track_color_off = QColor("#4c4c4c")
        self.track_color_on = QColor("#1DB954")  # Spotify green
        self.thumb_color = QColor("#FFFFFF")
        
        # Connect state change signals
        self.stateChanged.connect(self.on_state_changed)
    
    def sizeHint(self):
        """Return the recommended size for the widget."""
        return QSize(52, 26)
    
    def hitButton(self, pos):
        """Return True if pos is within the toggle switch."""
        return self.contentsRect().contains(pos)
    
    def on_state_changed(self, state):
        """Handle state changes and trigger animation."""
        self._enabled = state == Qt.Checked
        
        # Clean up existing animation
        if self.animation and self.animation.state() == self.animation.Running:
            self.animation.stop()
        
        # Create and start animation
        self.animation = QPropertyAnimation(self, b"thumb_position")
        self.animation.setDuration(self.animation_duration)
        self.animation.setStartValue(0 if not self._enabled else 1)
        self.animation.setEndValue(1 if self._enabled else 0)
        self.animation.setEasingCurve(QEasingCurve.InOutExpo)
        self.animation.start()
    
    def get_thumb_position(self):
        """Getter for thumb position property."""
        return self._thumb_position
    
    def set_thumb_position(self, position):
        """Setter for thumb position property with animation."""
        self._thumb_position = position
        self.update()
    
    # Define property for animation
    thumb_position = pyqtProperty(float, get_thumb_position, set_thumb_position)
    
    def paintEvent(self, event):
        """Custom paint event to draw the toggle switch."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Calculate rect and radius
        rect = self.rect()
        thumb_radius = (rect.height() - 2 * self._margin) / 2
        track_radius = rect.height() / 2
        
        # Calculate thumb position
        thumb_x = self._margin + self._thumb_position * (rect.width() - 2 * self._margin - 2 * thumb_radius)
        
        # Draw the track with appropriate color based on state and animation
        if self._enabled:
            track_color = self.track_color_on
        else:
            track_color = self.track_color_off
            
        # Create track path
        track_path = QPainterPath()
        track_path.addRoundedRect(QRectF(0, 0, rect.width(), rect.height()), track_radius, track_radius)
        
        # Fill track
        painter.fillPath(track_path, track_color)
        
        # Draw thumb
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.thumb_color)
        painter.drawEllipse(
            QPointF(thumb_x + thumb_radius, rect.height() / 2),
            thumb_radius,
            thumb_radius
        )


class ScriptWorker(QThread):
    """Worker thread for running Python scripts without blocking the UI."""
    
    update_progress = pyqtSignal(int, str)  # Progress value, status message
    script_finished = pyqtSignal(bool)  # Success/failure
    output_text = pyqtSignal(str)  # Output text for debug log
    console_output = pyqtSignal(str)  # Console output for display

    def __init__(self, script_path, script_name):
        """
        Initialize the script worker.
        
        Args:
            script_path (str): Path to the script
            script_name (str): Name of the script for display
        """
        super().__init__()
        self.script_path = script_path
        self.script_name = script_name
        self.process = None
        self.running = False
        self.start_time = None
        self.current_value = 0
        self.total_value = 100
        self.total_artists = 0
        self.processed_artists = 0
        self.extra_args = []  # Additional command line arguments
        
        # Add these variables for cumulative genre tracking
        self.total_genres = 0
        self.current_genre = 0
        self.total_artists_in_genres = 0
        self.processed_artists_in_genres = 0
        self.current_genre_name = ""
        self.current_genre_artists = 0
        self.current_genre_processed = 0
        
        # Log the initialization
        print(f"Initializing {script_name} worker for: {script_path}")
        
        # Progress tracking patterns - add patterns for genre processing
        self.progress_patterns = [
            # For ProgressBar updates (match percentage complete)
            re.compile(r'Progress.*?(\d+\.\d+)%'),
            # Look for "x/y artists" patterns to extract progress
            re.compile(r'Processed: (\d+)/(\d+) artists'),
            # Spotify playlist creation progress
            re.compile(r'Creating playlist \'(.+?)\' with (\d+) tracks'),
            # MusicBrainz related progress - detect starting to process an artist
            re.compile(r'=== PROCESSING: (.+?) ==='),
            # Progress bar with percentage
            re.compile(r'Progress: \|.+?\| (\d+\.\d+)% Complete'),
            # Genre progress pattern
            re.compile(r'Processing: (\d+)% \((\d+)/(\d+) genres\)'),
            # Processing genre with X artists
            re.compile(r'Processing genre: (.+?) with (\d+) artists'),
            # Processing up to X artists for genre
            re.compile(r'Processing up to (\d+) artists for genre: (.+)'),
            # Added tracks from artist X/Y
            re.compile(r'Added .+ track\(s\) from .+ \((\d+)/(\d+)\)')
        ]
        
        # Additional markers for music discovery script
        self.music_discovery_patterns = [
            re.compile(r'Found (\d+) unique artists'),
            re.compile(r'Finished processing .+ in \d+\.\d+ seconds'),
            re.compile(r'Total source artists with recommendations: (\d+)'),
            re.compile(r'Music discovery complete!')
        ]

    # Helper method to safely emit signals for output
    def safe_emit_output(self, message):
        """Safely emit output signals with proper error handling."""
        try:
            # Always print to console first
            print(f"WORKER: {message}")
            
            # Emit signals - these will be connected with Qt.QueuedConnection
            self.output_text.emit(message)
            self.console_output.emit(message)
        except Exception as e:
            print(f"Error emitting output: {e} - Message was: {message}")

    def find_venv_python(self, script_dir: str) -> str:
        """
        Find the Python executable in a virtual environment.
        
        Args:
            script_dir (str): Script directory to search for venv
            
        Returns:
            str: Path to Python executable or "python" if not found
        """
        # Try to locate virtual environment in the script directory
        if os.name == 'nt':  # Windows
            venv_paths = [
                os.path.join(script_dir, 'venv', 'Scripts', 'python.exe'),
                os.path.join(script_dir, '.venv', 'Scripts', 'python.exe'),
                os.path.join(script_dir, 'env', 'Scripts', 'python.exe'),
                os.path.join(script_dir, '.env', 'Scripts', 'python.exe')
            ]
        else:  # Linux/Mac
            venv_paths = [
                os.path.join(script_dir, 'venv', 'bin', 'python'),
                os.path.join(script_dir, '.venv', 'bin', 'python'),
                os.path.join(script_dir, 'env', 'bin', 'python'),
                os.path.join(script_dir, '.env', 'bin', 'python')
            ]
            
        # Check each possible venv path
        for path in venv_paths:
            if os.path.exists(path):
                self.safe_emit_output(f"Found virtual environment Python at: {path}")
                return path
                
        # If no venv found, use system Python
        self.safe_emit_output("No virtual environment found, using system Python")
        return "python"

    def run(self):
        """Run the script in a separate thread with non-blocking I/O handling."""
        self.running = True
        self.start_time = time.time()
        
        try:
            # Get the script directory
            script_dir = os.path.dirname(self.script_path)
            
            # Find the appropriate Python executable
            python_exe = self.find_venv_python(script_dir)
            
            # Build command including any extra arguments
            cmd = [python_exe, self.script_path] + self.extra_args
            
            # DETAILED DEBUG: Print exactly what we're trying to execute
            debug_cmd = f"Executing: {' '.join(cmd)}"
            self.safe_emit_output(debug_cmd)
            
            # Output current working directory for debugging
            cwd_msg = f"Working directory: {script_dir}"
            self.safe_emit_output(cwd_msg)
            
            # Set up startupinfo to hide console window (Windows only)
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':  # Windows
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
            
            # Prepare queues for thread-safe communication
            stdout_queue = queue.Queue()
            stderr_queue = queue.Queue()
            
            # Start the process with explicit error handling
            try:
                # Start the process
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,  # Line buffered
                    cwd=script_dir,
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
                self.safe_emit_output(f"Process started with PID: {self.process.pid}")
            except Exception as e:
                error_msg = f"Failed to start process: {str(e)}"
                self.safe_emit_output(error_msg)
                self.running = False
                self.script_finished.emit(False)
                return

            # Thread for reading stdout
            def enqueue_stdout():
                try:
                    for line in iter(self.process.stdout.readline, ''):
                        if line.strip():  # Only queue non-empty lines
                            stdout_queue.put(line.strip())
                    self.process.stdout.close()
                except Exception as e:
                    stdout_queue.put(f"STDOUT Error: {e}")

            # Thread for reading stderr
            def enqueue_stderr():
                try:
                    for line in iter(self.process.stderr.readline, ''):
                        if line.strip():  # Only queue non-empty lines
                            stderr_queue.put(line.strip())
                    self.process.stderr.close()
                except Exception as e:
                    stderr_queue.put(f"STDERR Error: {e}")

            # Create and start reader threads
            stdout_thread = threading.Thread(target=enqueue_stdout)
            stderr_thread = threading.Thread(target=enqueue_stderr)
            
            stdout_thread.daemon = True
            stderr_thread.daemon = True
            
            stdout_thread.start()
            stderr_thread.start()
            
            # Initial delay to ensure process has started
            time.sleep(0.2)
            
            # Check if process immediately failed
            if self.process.poll() is not None:
                self.safe_emit_output(f"Process exited immediately with code: {self.process.returncode}")
                self.running = False
                self.script_finished.emit(False)
                return
            
            # Monitor and process output
            while self.running and self.process.poll() is None:
                # Process stdout
                try:
                    while not stdout_queue.empty():
                        line = stdout_queue.get_nowait()
                        if line:
                            self.safe_emit_output(line)
                            self.update_progress_from_line(line)
                except queue.Empty:
                    pass
                
                # Process stderr
                try:
                    while not stderr_queue.empty():
                        line = stderr_queue.get_nowait()
                        if line:
                            error_msg = f"ERROR: {line}"
                            self.safe_emit_output(error_msg)
                except queue.Empty:
                    pass
                
                # Prevent tight loop
                time.sleep(0.1)
            
            # Wait for threads to finish
            stdout_thread.join(timeout=2.0)
            stderr_thread.join(timeout=2.0)
            
            # Get return code
            return_code = self.process.poll() or 0
            
            # Final processing of any remaining output
            while not stdout_queue.empty():
                line = stdout_queue.get()
                if line:
                    self.safe_emit_output(line)
            
            while not stderr_queue.empty():
                line = stderr_queue.get()
                if line:
                    error_msg = f"ERROR: {line}"
                    self.safe_emit_output(error_msg)
            
            # Log completion status
            finish_msg = f"Process finished with return code: {return_code}"
            self.safe_emit_output(finish_msg)
            
            # Signal completion
            self.script_finished.emit(return_code == 0)
            
        except Exception as e:
            error = f"Error running script: {str(e)}\n{traceback.format_exc()}"
            self.safe_emit_output(error)
            self.running = False
            self.script_finished.emit(False)
        finally:
            self.running = False

    def update_progress_from_line(self, line: str) -> bool:
        """
        Extract progress information from log lines with improved status messaging.
        
        Args:
            line (str): Log line to process
            
        Returns:
            bool: True if progress was updated, False otherwise
        """
        try:
            # First, check for genre-related progress indicators
            
            # Check for genre progress pattern: Processing: X% (Y/Z genres)
            genre_progress_match = re.search(r'Processing: (\d+)% \((\d+)/(\d+) genres\)', line)
            if genre_progress_match:
                percentage = int(genre_progress_match.group(1))
                current = int(genre_progress_match.group(2))
                total = int(genre_progress_match.group(3))
                
                # Update our tracking variables
                self.current_genre = current
                self.total_genres = total
                
                # Reset the artist counters for the new genre
                self.current_genre_processed = 0
                
                # For progress percentage, we'll use the overall genre percentage
                # but we'll show both genre progress and cumulative artist progress in the status
                self.update_progress.emit(
                    percentage, 
                    f"Genres: {current}/{total} ({percentage}%) - Artists: {self.processed_artists_in_genres}/{self.total_artists_in_genres}"
                )
                self.current_value = percentage
                return True
            
            # Check for "Processing genre: X with Y artists"
            genre_artists_match = re.search(r'Processing genre: (.+?) with (\d+) artists', line)
            if genre_artists_match:
                genre_name = genre_artists_match.group(1)
                artists_count = int(genre_artists_match.group(2))
                
                # Update our tracking variables
                self.current_genre_name = genre_name
                self.current_genre_artists = artists_count
                self.total_artists_in_genres += artists_count
                
                # Update the status but don't change the progress percentage
                status_message = f"Processing genre: {genre_name} ({self.current_genre}/{self.total_genres}) with {artists_count} artists"
                self.update_progress.emit(-6, status_message)
                return True
            
            # Check for "Processing up to X artists for genre: Y"
            processing_up_to_match = re.search(r'Processing up to (\d+) artists for genre: (.+)', line)
            if processing_up_to_match:
                artists_to_process = int(processing_up_to_match.group(1))
                genre_name = processing_up_to_match.group(2)
                
                # This updates how many we'll actually process (may be less than total)
                if artists_to_process < self.current_genre_artists:
                    # Adjust our total to be more accurate
                    self.total_artists_in_genres -= (self.current_genre_artists - artists_to_process)
                    self.current_genre_artists = artists_to_process
                
                # Update the status but don't change the progress percentage
                status_message = f"Processing {artists_to_process} artists for genre: {genre_name} ({self.current_genre}/{self.total_genres})"
                self.update_progress.emit(-6, status_message)
                return True
            
            # Check for "Added X track(s) from Artist (Y/Z)"
            artist_track_match = re.search(r'Added .+ track\(s\) from .+ \((\d+)/(\d+)\)', line)
            if artist_track_match:
                current_artist = int(artist_track_match.group(1))
                total_artists = int(artist_track_match.group(2))
                
                # Update our tracking for the current genre
                self.current_genre_processed = current_artist
                
                # Update our cumulative artist count
                if current_artist > self.current_genre_processed:
                    self.processed_artists_in_genres += 1
                
                # Calculate overall progress
                overall_percentage = 0
                if self.total_artists_in_genres > 0:
                    overall_percentage = int((self.processed_artists_in_genres / self.total_artists_in_genres) * 100)
                
                # Create a status message showing both the current genre progress and cumulative progress
                genre_progress = f"{current_artist}/{total_artists}"
                cumulative_progress = f"{self.processed_artists_in_genres}/{self.total_artists_in_genres}"
                
                status_message = f"Genre {self.current_genre_name}: {genre_progress} artists - Overall: {cumulative_progress} artists"
                
                # Emit the progress update - we'll calculate percentage based on completed genres + partial current genre
                genre_percentage = int(self.current_genre / self.total_genres * 100)
                genre_fraction = (current_artist / total_artists) / self.total_genres
                adjusted_percentage = genre_percentage - (100 / self.total_genres) + int(genre_fraction * 100)
                
                # Make sure the progress is always increasing
                if adjusted_percentage > self.current_value:
                    self.current_value = adjusted_percentage
                
                self.update_progress.emit(self.current_value, status_message)
                return True
            
            # If no genre-specific patterns match, fall back to the original logic
            
            # Check for total artists initialization
            total_artists_match = re.search(r'JSON file contains (\d+) total unique artists to process', line)
            if total_artists_match:
                total = int(total_artists_match.group(1))
                self.total_artists = total
                self.safe_emit_output(f"Initialized total artists to {total}")
                self.update_progress.emit(0, f"Beginning to process {total} artists")
                return True
            
            # Specifically look for progress lines with detailed format
            progress_match = re.search(r'Progress: (\d+\.\d+)% \((\d+)/(\d+) artists\)', line)
            if progress_match:
                percentage = float(progress_match.group(1))
                current = int(progress_match.group(2))
                total = int(progress_match.group(3))
                
                # Convert percentage to integer and emit progress update
                int_percentage = int(percentage)
                self.update_progress.emit(int_percentage, f"Processing: {current}/{total} artists")
                self.current_value = int_percentage
                return True
            
            # Detect scanning library
            if "Scanning music library in" in line:
                dir_match = re.search(r'Scanning music library in (.+?)\.\.\.', line)
                if dir_match:
                    music_dir = dir_match.group(1)
                    self.update_progress.emit(2, f"Scanning library in {music_dir}")
                    return True
            
            # Detect artist directory counting
            if "Found" in line and "artist directories with" in line:
                dirs_match = re.search(r'Found (\d+) artist directories with (\d+) potential album directories', line)
                if dirs_match:
                    artists = dirs_match.group(1)
                    albums = dirs_match.group(2)
                    self.update_progress.emit(5, f"Found {artists} artists with {albums} albums")
                    return True
            
            # Detect processing a specific artist
            artist_processing = re.search(r'=== PROCESSING: (.+?) ===', line)
            if artist_processing:
                artist_name = artist_processing.group(1)
                # Truncate long artist names for display
                if len(artist_name) > 30:
                    artist_name = artist_name[:27] + "..."
                self.update_progress.emit(-3, f"Processing artist: {artist_name}")
                return True
            
            # Detect Spotify progress format
            spotify_progress_match = re.search(r'Progress: (\d+\.\d+)%', line)
            if spotify_progress_match and not progress_match:  # Make sure we didn't already match above
                percentage = float(spotify_progress_match.group(1))
                int_percentage = int(percentage)
                self.update_progress.emit(int_percentage, f"Processing: {int_percentage}% complete")
                self.current_value = int_percentage
                return True
            
            # Detect phase transition to playlist generation
            if any(marker in line.lower() for marker in [
                "starting playlist generation", 
                "processing artists in genre",
                "adding artists to playlist",
                "creating playlist"
            ]):
                # Signal phase transition without setting progress to 100%
                self.update_progress.emit(-2, "Starting Playlist Generation")
                return True
            
            # Detect creating a specific playlist
            playlist_match = re.search(r"Creating playlist '(.+?)' with (\d+) tracks", line)
            if playlist_match:
                playlist_name = playlist_match.group(1)
                tracks = playlist_match.group(2)
                self.update_progress.emit(-4, f"Creating playlist: {playlist_name} ({tracks} tracks)")
                return True
            
            # Detect successful playlist creation
            if "Playlist URL:" in line:
                playlist_url_match = re.search(r"Playlist URL: (https://open\.spotify\.com/playlist/\w+)", line)
                if playlist_url_match:
                    self.update_progress.emit(-5, "Playlist created successfully")
                    return True
            
            # Detect organizing tracks for a specific artist
            organize_match = re.search(r"Organizing tracks for artist: (.+)", line)
            if organize_match:
                artist = organize_match.group(1)
                if len(artist) > 30:
                    artist = artist[:27] + "..."
                self.update_progress.emit(-7, f"Finding tracks for: {artist}")
                return True
            
            # Detect artist genre classification
            if "Genre Lookup Summary:" in line:
                self.update_progress.emit(-1, "Artist Genre Classification Complete")
                return True
            
            # Detect library artists summary
            library_match = re.search(r"Found (\d+) unique artists in (\d+) valid FLAC files", line)
            if library_match:
                artists_count = library_match.group(1)
                files_count = library_match.group(2)
                self.update_progress.emit(95, f"Found {artists_count} artists in {files_count} files")
                return True
            
            # Detect successful recommendations
            if "Total source artists with recommendations:" in line:
                rec_match = re.search(r"Total source artists with recommendations: (\d+)", line)
                if rec_match:
                    count = rec_match.group(1)
                    self.update_progress.emit(97, f"Generated recommendations for {count} artists")
                    return True
            
            # Detect saving recommendations
            if "Saving recommendations" in line:
                self.update_progress.emit(98, "Saving recommendations to file")
                return True
            
            # Detect completion of music discovery
            if "Music discovery complete" in line:
                self.update_progress.emit(100, "Music Discovery completed successfully")
                return True
            
            # Return false if no progress was detected
            return False
            
        except Exception as e:
            # Log errors in progress tracking
            error_msg = f"Error in progress tracking: {str(e)}\n{traceback.format_exc()}"
            self.safe_emit_output(error_msg)
            return False

    def stop(self):
        """Stop the running process safely."""
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                # Give it a moment to terminate gracefully
                for _ in range(10):
                    if self.process.poll() is not None:
                        self.safe_emit_output("Process terminated gracefully")
                        break
                    time.sleep(0.1)
                
                # Force kill if still running
                if self.process.poll() is None:
                    self.process.kill()
                    self.safe_emit_output("Process killed forcefully")
            except Exception as e:
                self.safe_emit_output(f"Error stopping process: {str(e)}")


class SpotifyLauncher(QMainWindow):
    """Main window for the Spotify Launcher application."""
    
    def __init__(self):
        """Initialize the Spotify Launcher."""
        super().__init__()
        
        # Initialize last button clicked tracking
        self.last_button_clicked = None
        
        self.phase2_active = False
        
        # Configure window
        self.setWindowTitle("GenreGenius")
        self.setMinimumSize(700, 700)  # Larger window to accommodate console output
        
        # Set up central widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Upper section for controls
        upper_widget = QWidget()
        upper_layout = QVBoxLayout(upper_widget)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        
        # Title label with musical notes
        title = QLabel("♫  GenreGenius ♫")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 16, QFont.Bold))
        upper_layout.addWidget(title)
        
        # Add spacer
        upper_layout.addSpacing(20)
        
        # Music Discovery button and progress section
        discovery_layout = QVBoxLayout()
        
        # Button
        self.discovery_button = QPushButton("Step 1: Music Discovery")
        self.discovery_button.setFont(QFont("Arial", 12))
        self.discovery_button.setMinimumHeight(50)
        self.discovery_button.clicked.connect(self.launch_music_discovery)
        discovery_layout.addWidget(self.discovery_button)
        
        # Progress bar
        self.discovery_progress = ColourProgressBar()
        self.discovery_progress.setRange(0, 100)
        self.discovery_progress.setValue(0)
        self.discovery_progress.setFormat("")  # Clear the default format
        self.discovery_progress.setTextVisible(False)  # Hide text
        discovery_layout.addWidget(self.discovery_progress)
        
        # Status
        discovery_status_layout = QHBoxLayout()
        self.discovery_status = QLabel("Ready")
        discovery_status_layout.addWidget(self.discovery_status)
        discovery_layout.addLayout(discovery_status_layout)
        
        upper_layout.addLayout(discovery_layout)
        
        # Add spacer
        upper_layout.addSpacing(20)
        
        # Spotify Client button and progress section
        spotify_layout = QVBoxLayout()
        
        # Button
        self.spotify_button = QPushButton("Step 2: Create Spotify Playlists")
        self.spotify_button.setFont(QFont("Arial", 12))
        self.spotify_button.setMinimumHeight(50)
        self.spotify_button.clicked.connect(self.launch_spotify_client)
        spotify_layout.addWidget(self.spotify_button)
        
        # First phase label
        self.spotify_phase1_label = QLabel("Phase 1: Artist Genre Classification")
        spotify_layout.addWidget(self.spotify_phase1_label)
        
        # First progress bar - for artist genre classification
        self.spotify_progress1 = ColourProgressBar()
        self.spotify_progress1.setRange(0, 100)
        self.spotify_progress1.setValue(0)
        self.spotify_progress1.setFormat("")
        self.spotify_progress1.setTextVisible(False)
        spotify_layout.addWidget(self.spotify_progress1)
        
        # First phase status
        spotify_status1_layout = QHBoxLayout()
        self.spotify_status1 = QLabel("Ready")
        spotify_status1_layout.addWidget(self.spotify_status1)
        spotify_layout.addLayout(spotify_status1_layout)
        
        # Add a small spacer
        spotify_layout.addSpacing(5)
        
        # Second phase label
        self.spotify_phase2_label = QLabel("Phase 2: Playlist Generation")
        spotify_layout.addWidget(self.spotify_phase2_label)
        
        # Second progress bar - for playlist generation
        self.spotify_progress2 = ColourProgressBar()
        self.spotify_progress2.setRange(0, 100)
        self.spotify_progress2.setValue(0)
        self.spotify_progress2.setFormat("")
        self.spotify_progress2.setTextVisible(False)
        spotify_layout.addWidget(self.spotify_progress2)
        
        # Second phase status
        spotify_status2_layout = QHBoxLayout()
        self.spotify_status2 = QLabel("Ready")
        spotify_status2_layout.addWidget(self.spotify_status2)
        spotify_layout.addLayout(spotify_status2_layout)
        
        upper_layout.addLayout(spotify_layout)
        
        # Add the upper section to main layout
        main_layout.addWidget(upper_widget)
        
        # Tabbed console output section
        self.output_tabs = QTabWidget()
        
        # Tab for Music Discovery output
        self.discovery_output = QTextEdit()
        self.discovery_output.setReadOnly(True)
        self.discovery_output.setFont(QFont("Consolas", 9))
        self.output_tabs.addTab(self.discovery_output, "Music Discovery Output")
        
        # Tab for Spotify Client output
        self.spotify_output = QTextEdit()
        self.spotify_output.setReadOnly(True)
        self.spotify_output.setFont(QFont("Consolas", 9))
        self.output_tabs.addTab(self.spotify_output, "Spotify Client Output")
        
        # Tab for debug output (hidden by default)
        self.debug_output = QTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setFont(QFont("Consolas", 9))
        
        # Add the output tabs to the main layout
        main_layout.addWidget(self.output_tabs)
        
        # Create actions for toggling views
        # Default to OFF for both console and debug tab
        self.toggle_console_action = QAction('Show Console Output', self, checkable=True)
        self.toggle_console_action.setChecked(False)  # Default OFF on first run
        self.toggle_console_action.triggered.connect(self.safe_toggle_console_output)
        
        self.toggle_debug_action = QAction('Show Debug Tab', self, checkable=True)
        self.toggle_debug_action.setChecked(False)  # Default OFF on first run
        self.toggle_debug_action.triggered.connect(self.safe_toggle_debug_tab)
        
        # Set up the menu bar (after creating toggle actions)
        self.setup_menu()
        
        # Store process references
        self.discovery_worker = None
        self.spotify_worker = None
        
        # Create thread-safe logger
        self.logger = ThreadSafeLogger()
        self.logger.setParent(self)  # Set parent to access truncate_status method
        
        # Load and set the icon
        self.load_set_icon()
        
        # Log startup information
        self.log_status("Application started")
        self.log_status(f"Running from: {self.get_base_dir()}")
        # Log Python version
        self.log_status(f"Python version: {sys.version}")
        
        # Hide debug tab by default - before loading settings
        self.toggle_debug_tab(False)
        
        # Apply dark theme
        self.apply_dark_theme()
        
        # Set up tab changed tracking
        self.output_tabs.currentChanged.connect(self.tab_changed)
        
        # Set app and window title to dark
        palette = self.palette()
        dark_bg = QColor("#121212")
        palette.setColor(QPalette.Window, dark_bg)
        palette.setColor(QPalette.WindowText, QColor("#E0E0E0"))
        self.setPalette(palette)
        
        # Load saved settings from config file - this will override defaults if config exists
        self.load_settings()
        
        # Apply dark theme to titlebar - after all other UI initialization
        self.apply_dark_theme_to_titlebar()

    def event(self, event):
        """
        Custom event handler to process log events in the main thread.
        
        Args:
            event (QEvent): Event to process
            
        Returns:
            bool: True if event was handled, otherwise result of parent implementation
        """
        if event.type() == LogEvent.EVENT_TYPE:
            event.callback()
            return True
        return super().event(event)

    def tab_changed(self, index):
        """
        Handle tab change events to maintain scroll position.
        
        Args:
            index (int): Index of the selected tab
        """
        try:
            # Get the current widget
            current_widget = self.output_tabs.widget(index)
            
            # Ensure scroll to bottom for text edit widgets
            if isinstance(current_widget, QTextEdit):
                # Use the scrollbar directly for safe scrolling
                scroll_bar = current_widget.verticalScrollBar()
                if scroll_bar:
                    scroll_bar.setValue(scroll_bar.maximum())
        except Exception as e:
            print(f"Error in tab_changed: {str(e)}")

    def toggle_maximize(self):
        """Toggle between maximized and normal window state."""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def apply_dark_theme_to_titlebar(self):
        """Apply dark theme to the window title bar with light text."""
        try:
            # Define Windows API constants
            DWMWA_CAPTION_COLOR = 35  # DWM caption color attribute
            DWMWA_TEXT_COLOR = 36     # DWM caption text color attribute
            
            # Dark title bar color (#121212) in COLORREF format
            dark_title_color = 0x00121212
            
            # Light text color (white #FFFFFF) in COLORREF format
            light_text_color = 0x00FFFFFF
            
            # Apply the dark color to the title bar
            windll.dwmapi.DwmSetWindowAttribute(
                int(self.winId()),
                DWMWA_CAPTION_COLOR,
                byref(c_int(dark_title_color)),
                sizeof(c_int)
            )
            
            # Apply the light text color to the title bar
            windll.dwmapi.DwmSetWindowAttribute(
                int(self.winId()),
                DWMWA_TEXT_COLOR,
                byref(c_int(light_text_color)),
                sizeof(c_int)
            )
            
            self.log_status("Applied dark theme to Windows title bar")
        except Exception as e:
            self.log_status(f"Error setting Windows title bar color: {str(e)}")
            # Fallback method
            try:
                self.setStyleSheet(self.styleSheet() + """
                    QMainWindow::title {
                        background-color: #121212;
                        color: white;
                    }
                """)
                self.log_status("Applied fallback dark title styling")
            except Exception as e:
                self.log_status(f"Error in fallback title styling: {str(e)}")

    def apply_dark_theme(self):
        """Apply a dark theme with modern colors to the application."""
        # Dark theme color palette
        dark_bg = "#121212"              # Main dark background
        darker_bg = "#0A0A0A"            # Darker accent background
        dark_accent = "#1F1F1F"          # Slightly lighter accent
        text_color = "#E0E0E0"           # Light text color
        muted_text = "#AAAAAA"           # Muted text for less important elements
        spotify_green = "#1DB954"        # Spotify green for highlights
        spotify_green_hover = "#1ED760"  # Lighter green for hover states
        spotify_green_pressed = "#169C46" # Darker green for pressed states
        border_color = "#333333"         # Border color for elements
        
        # Progress bar colors
        progress_bg = "#282828"          # Progress bar background
        
        # Tab colors
        tab_bg = "#282828"               # Tab background
        tab_selected = "#1F1F1F"         # Selected tab
        tab_hover = "#333333"            # Hovered tab
        
        # Set main window background color
        self.central_widget.setStyleSheet(f"background-color: {dark_bg};")
        
        # Style for rounded buttons with Spotify green
        button_style = f"""
            QPushButton {{
                border-radius: 8px;
                background-color: {spotify_green};
                border: none;
                padding: 8px 16px;
                color: white;
                font-weight: bold;
            }}
            
            QPushButton:hover {{
                background-color: {spotify_green_hover};
            }}
            
            QPushButton:pressed {{
                background-color: {spotify_green_pressed};
            }}
            
            QPushButton:disabled {{
                background-color: #444444;
                color: #777777;
            }}
        """
        
        # Style for text areas (QTextEdit)
        textedit_style = f"""
            QTextEdit {{
                border-radius: 4px;
                border: 1px solid {border_color};
                padding: 5px;
                background-color: {dark_accent};
                color: {text_color};
            }}
        """
        
        # Apply styles to buttons
        self.discovery_button.setStyleSheet(button_style)
        self.spotify_button.setStyleSheet(button_style)
        
        # Apply styles to text areas
        self.discovery_output.setStyleSheet(textedit_style)
        self.spotify_output.setStyleSheet(textedit_style)
        self.debug_output.setStyleSheet(textedit_style)
        
        # Style for the tab widget to match the dark theme
        tab_style = f"""
            QTabWidget::pane {{
                border-radius: 4px;
                border: 1px solid {border_color};
                background-color: {dark_accent};
            }}
            
            QTabBar::tab {{
                border-radius: 4px 4px 0 0;
                padding: 5px 10px;
                margin-right: 2px;
                background-color: {tab_bg};
                color: {muted_text};
            }}
            
            QTabBar::tab:selected {{
                background-color: {tab_selected};
                color: {text_color};
            }}
            
            QTabBar::tab:hover:!selected {{
                background-color: {tab_hover};
            }}
        """
        self.output_tabs.setStyleSheet(tab_style)
        
        # Style for labels
        label_style = f"""
            QLabel {{
                color: {text_color};
            }}
        """
        self.spotify_phase1_label.setStyleSheet(label_style)
        self.spotify_phase2_label.setStyleSheet(label_style)
        self.discovery_status.setStyleSheet(label_style)
        self.spotify_status1.setStyleSheet(label_style)
        self.spotify_status2.setStyleSheet(label_style)
        
        # Make the title label bright and prominent
        title_style = f"""
            QLabel {{
                color: {spotify_green};
                font-weight: bold;
                font-size: 18px;
            }}
        """
        
        # Find the title label in your UI
        for child in self.findChildren(QLabel):
            if "♫  GenreGenius ♫" in child.text():
                child.setStyleSheet(title_style)
                break
        
        # Update menu bar to dark theme
        menubar_style = f"""
            QMenuBar {{
                background-color: {dark_bg};
                color: {text_color};
            }}
            QMenuBar::item {{
                background-color: {dark_bg};
                color: {text_color};
            }}
            QMenuBar::item:selected {{
                background-color: {dark_accent};
            }}
            QMenu {{
                background-color: {dark_bg};
                color: {text_color};
                border: 1px solid {border_color};
            }}
            QMenu::item:selected {{
                background-color: {dark_accent};
            }}
        """
        self.menuBar().setStyleSheet(menubar_style)
        
        # Set window background and title bar color
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {dark_bg};
            }}
            QStatusBar {{
                background-color: {dark_bg};
                color: {text_color};
            }}
        """)

        # Overwrite the custom color progress bar style with dark theme
        self.discovery_progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {border_color};
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                color: white;
                height: 25px;
                background-color: {progress_bg};
            }}

            QProgressBar::chunk {{
                background-color: {spotify_green};
                width: 10px;
                margin: 0.5px;
            }}
        """)
        
        self.spotify_progress1.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {border_color};
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                color: white;
                height: 25px;
                background-color: {progress_bg};
            }}

            QProgressBar::chunk {{
                background-color: {spotify_green};
                width: 10px;
                margin: 0.5px;
            }}
        """)
        
        self.spotify_progress2.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {border_color};
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                color: white;
                height: 25px;
                background-color: {progress_bg};
            }}

            QProgressBar::chunk {{
                background-color: {spotify_green};
                width: 10px;
                margin: 0.5px;
            }}
        """)

    
    def print_banner(self):
        """Print a colorful banner in the log."""
        banner = """
    ╔═══════════════════════════════════════════════╗
    ║  FLAC Music Discovery App - Find New Artists  ║
    ╚═══════════════════════════════════════════════╝
    """
        # Log the banner to the discovery output
        self.log_discovery_output(banner)
        
        # Also log to the status/debug output
        self.log_status("Music Discovery process started")

    def is_configuration_valid(self):
        """Check if a valid configuration exists."""
        config_path = os.path.join(self.get_base_dir(), "config.json")
        
        if not os.path.exists(config_path):
            return False
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                music_dir = config.get("music_directory")
                
                # Check if music directory exists
                if not music_dir or not os.path.isdir(music_dir):
                    return False
                    
                # Check for UI settings - they're optional, so just log if missing
                if "debug_tab_enabled" not in config:
                    self.log_status("Warning: debug_tab_enabled not found in config")
                    
                if "console_output_enabled" not in config:
                    self.log_status("Warning: console_output_enabled not found in config")
                    
                return True
        except Exception as e:
            self.log_status(f"Error checking configuration: {str(e)}")
            return False

    def browse_music_dir(self, input_field):
        """
        Open file browser to select music directory.
        
        Args:
            input_field (QLineEdit): The text field to update with the selected path
        """
        directory = QFileDialog.getExistingDirectory(
            self, 
            "Select Music Directory",
            input_field.text()
        )
        if directory:
            input_field.setText(directory)

    def apply_dark_theme_to_titlebar(self):
        """Apply dark theme to the window title bar with light text."""
        try:
            # Define Windows API constants
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20   # Immersive dark mode for title bar
            DWMWA_CAPTION_COLOR = 35             # DWM caption color attribute
            DWMWA_TEXT_COLOR = 36                # DWM caption text color attribute
            
            # Dark title bar color (#121212) in COLORREF format
            dark_title_color = 0x00121212
            
            # Light text color (white #FFFFFF) in COLORREF format
            light_text_color = 0x00FFFFFF
            
            # Get the window handle
            hWnd = int(self.winId())
            
            # First try setting immersive dark mode (Windows 10 1809+)
            try:
                immersive_dark_mode = c_int(1)  # TRUE
                windll.dwmapi.DwmSetWindowAttribute(
                    hWnd,
                    DWMWA_USE_IMMERSIVE_DARK_MODE,
                    byref(immersive_dark_mode),
                    sizeof(c_int)
                )
                self.log_status("Applied immersive dark mode to Windows title bar")
            except Exception as e:
                # If immersive dark mode fails, use the color attributes as fallback
                self.log_status(f"Immersive dark mode not available: {str(e)}. Falling back to caption color.")
            
            # Apply the dark color to the title bar
            windll.dwmapi.DwmSetWindowAttribute(
                hWnd,
                DWMWA_CAPTION_COLOR,
                byref(c_int(dark_title_color)),
                sizeof(c_int)
            )
            
            # Apply the light text color to the title bar
            windll.dwmapi.DwmSetWindowAttribute(
                hWnd,
                DWMWA_TEXT_COLOR,
                byref(c_int(light_text_color)),
                sizeof(c_int)
            )
            
            self.log_status("Applied dark theme to Windows title bar")
        except Exception as e:
            self.log_status(f"Error setting Windows title bar color: {str(e)}")
            # Fallback method
            try:
                self.setStyleSheet(self.styleSheet() + """
                    QMainWindow::title {
                        background-color: #121212;
                        color: white;
                    }
                """)
                self.log_status("Applied fallback dark title styling")
            except Exception as e:
                self.log_status(f"Error in fallback title styling: {str(e)}")

    def apply_dark_style_to_message_box(self, message_box):
        """
        Apply dark mode styling to a QMessageBox.
        
        Args:
            message_box (QMessageBox): The message box to style
        """
        # Dark theme color palette
        dark_bg = "#121212"              # Main dark background
        darker_bg = "#0A0A0A"            # Darker accent background
        dark_accent = "#1F1F1F"          # Slightly lighter accent
        text_color = "#E0E0E0"           # Light text color
        spotify_green = "#1DB954"        # Spotify green
        border_color = "#333333"         # Border color
        
        # Style the message box
        message_box.setStyleSheet(f"""
            QMessageBox {{
                background-color: {dark_bg};
                color: {text_color};
            }}
            QLabel {{
                color: {text_color};
                font-size: 12px;
            }}
            QPushButton {{
                background-color: {spotify_green};
                color: white;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                border: none;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background-color: #1ED760;
            }}
            QPushButton:pressed {{
                background-color: #169C46;
            }}
        """)
        
        # Attempt to set window icon if available
        if hasattr(self, 'windowIcon') and callable(getattr(self, 'windowIcon')):
            message_box.setWindowIcon(self.windowIcon())
            
        # Apply dark title bar - we need to do this after the dialog is created but before it's shown
        message_box.setProperty("darkMode", True)
        
        # Get all child widgets to ensure they inherit the right styling
        for child in message_box.findChildren(QPushButton):
            child.setStyleSheet(f"""
                QPushButton {{
                    background-color: {spotify_green};
                    color: white;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: bold;
                    border: none;
                    min-width: 80px;
                }}
                QPushButton:hover {{
                    background-color: #1ED760;
                }}
                QPushButton:pressed {{
                    background-color: #169C46;
                }}
            """)
        
        # Apply the dark title bar using Windows API (for Windows only)
        try:
            if sys.platform == 'win32':
                # Define Windows API constants
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20   # Immersive dark mode for title bar
                DWMWA_CAPTION_COLOR = 35             # DWM caption color attribute
                DWMWA_TEXT_COLOR = 36                # DWM caption text color attribute
                
                # Dark title bar color (#121212) in COLORREF format
                dark_title_color = 0x00121212
                
                # Light text color (white #FFFFFF) in COLORREF format
                light_text_color = 0x00FFFFFF
                
                # Get the window handle
                hWnd = int(message_box.winId())
                
                # First try setting immersive dark mode (Windows 10 1809+)
                try:
                    immersive_dark_mode = c_int(1)  # TRUE
                    windll.dwmapi.DwmSetWindowAttribute(
                        hWnd,
                        DWMWA_USE_IMMERSIVE_DARK_MODE,
                        byref(immersive_dark_mode),
                        sizeof(c_int)
                    )
                except Exception as e:
                    # If immersive dark mode fails, use the color attributes as fallback
                    pass
                    
                # Apply the dark color to the title bar
                windll.dwmapi.DwmSetWindowAttribute(
                    hWnd,
                    DWMWA_CAPTION_COLOR,
                    byref(c_int(dark_title_color)),
                    sizeof(c_int)
                )
                
                # Apply the light text color to the title bar
                windll.dwmapi.DwmSetWindowAttribute(
                    hWnd,
                    DWMWA_TEXT_COLOR,
                    byref(c_int(light_text_color)),
                    sizeof(c_int)
                )
        except Exception as e:
            print(f"Error setting title bar color: {e}")
            # Fallback method if needed
            message_box.setStyleSheet(message_box.styleSheet() + f"""
                QDialog::title {{
                    background-color: {dark_bg};
                    color: {text_color};
                }}
            """)

    def launch_music_discovery(self):
        """Launch the Music Discovery script with progress tracking."""
        # Set the last button clicked
        self.last_button_clicked = 'discovery'
        
        # Check if configuration exists
        if not self.is_configuration_valid():
            self.log_status("No valid configuration found. Showing options dialog.")
            self.show_options_dialog()
            return
            
        # Clear the last button clicked as we're proceeding normally
        self.last_button_clicked = None
        
        # Run the actual process
        self.run_music_discovery()

    def launch_spotify_client(self):
        """Launch the Spotify Client script with progress tracking."""
        # Set the last button clicked
        self.last_button_clicked = 'spotify'
        
        # Check if configuration exists
        if not self.is_configuration_valid():
            self.log_status("No valid configuration found. Showing options dialog.")
            self.show_options_dialog()
            return
            
        # Clear the last button clicked as we're proceeding normally
        self.last_button_clicked = None
        
        # Run the actual process
        self.run_spotify_client()

    def run_spotify_client(self):
        """Run the actual Spotify Client process."""    
        # Skip configuration check since we're called after that
        if self.spotify_worker and self.spotify_worker.isRunning():
            # Script is already running
            self.log_status("Spotify Client is already running")
            return
                
        # Reset UI for all progress bars - ensure they're explicitly set to 0
        self.spotify_progress1.setValue(0)
        self.spotify_progress2.setValue(0)
        
        # Clear all text labels
        self.spotify_status1.setText("")
        self.spotify_status2.setText("")
        
        # Reset phase flag
        self.phase2_active = False
        
        # Disable buttons
        self.spotify_button.setEnabled(False)
        self.discovery_button.setEnabled(False)
        
        # Clear the output text
        self.spotify_output.clear()
        
        # Activate the Spotify Client output tab
        self.output_tabs.setCurrentWidget(self.spotify_output)
                
        # Find the script
        spotify_script = None
        for script_name in ["spotifyclient.py"]:
            script_path = self.find_script(script_name)
            if script_path:
                spotify_script = script_path
                self.log_status(f"Found Spotify client script: {script_name}")
                break
                    
        if not spotify_script:
            self.log_status("ERROR: Could not find any Spotify client script!")
            self.spotify_button.setEnabled(True)
            self.discovery_button.setEnabled(True)  # Re-enable Music Discovery button
            return
        
        try:
            # Get configured music directory from config file
            music_dir = self.get_configured_music_dir()
            
            # Construct path to recommendations.json file
            recommendations_file = os.path.join(music_dir, "recommendations.json")
            
            # Check if recommendations file exists
            if not os.path.exists(recommendations_file):
                self.log_spotify_output(f"Error: Recommendations file not found: {recommendations_file}")
                self.log_spotify_output("Please run Music Discovery first.")
                self.spotify_button.setEnabled(True)
                self.discovery_button.setEnabled(True)
                return
                
            # Create and start the worker thread
            self.spotify_worker = ScriptWorker(spotify_script, "Spotify Client")
            
            # Connect signals
            self.spotify_worker.update_progress.connect(self.update_spotify_progress)
            self.spotify_worker.script_finished.connect(self.spotify_finished)
            self.spotify_worker.output_text.connect(self.log_status)
            self.spotify_worker.console_output.connect(self.log_spotify_output)
            
            # Add the recommendations file as environment variable
            os.environ["RECOMMENDATIONS_FILE"] = recommendations_file
            self.log_status(f"Set RECOMMENDATIONS_FILE environment variable: {recommendations_file}")
            
            # Start the thread
            self.spotify_worker.start()
            
            # Log the start of the process
            self.log_status("Spotify Client started")
            self.log_spotify_output(f"Spotify Client process started using recommendations file: {recommendations_file}...")
        
        except Exception as e:
            error_msg = f"Error launching Spotify Client: {str(e)}\n{traceback.format_exc()}"
            self.log_status(error_msg)
            self.log_spotify_output(f"ERROR: {str(e)}")
            
            # Re-enable buttons on error
            self.spotify_button.setEnabled(True)
            self.discovery_button.setEnabled(True)

    def run_music_discovery(self):
        """Run the actual Music Discovery process."""
        # Skip configuration check since we're called after that
        if self.discovery_worker and self.discovery_worker.isRunning():
            self.log_status("Music Discovery is already running")
            return

        # Reset UI - clear the status text before showing dialog
        self.discovery_progress.setValue(0)
        self.discovery_status.setText("")  # Clear status text completely
        self.discovery_button.setEnabled(False)
        
        # Disable the Spotify button while Music Discovery is running
        self.spotify_button.setEnabled(False)

        # Clear the output text
        self.discovery_output.clear()

        # Activate the Music Discovery output tab
        self.output_tabs.setCurrentWidget(self.discovery_output)

        # Get configured music directory from config file
        music_dir = self.get_configured_music_dir()
        
        # Check if the music directory exists
        if not os.path.isdir(music_dir):
            error_msg = f"Music directory does not exist: {music_dir}"
            self.log_status(error_msg)
            self.log_discovery_output(f"ERROR: {error_msg}")
            self.discovery_status.setText("Error: Directory not found")
            self.discovery_button.setEnabled(True)
            self.spotify_button.setEnabled(True)
            
            # Show error message to user
            error_dialog = QMessageBox(self)
            error_dialog.setWindowTitle("Music Directory Error")
            error_dialog.setText(f"The music directory does not exist:\n{music_dir}\n\nPlease select a valid directory in Settings.")
            error_dialog.setIcon(QMessageBox.Critical)
            self.apply_dark_style_to_message_box(error_dialog)
            error_dialog.exec_()
            
            # Set flag to show options dialog on next button press
            self.last_button_clicked = 'discovery_error'
            return
        
        # Check if there are any subdirectories in the music directory
        has_subdirs = False
        try:
            for item in os.listdir(music_dir):
                subdir_path = os.path.join(music_dir, item)
                if os.path.isdir(subdir_path):
                    has_subdirs = True
                    break
                    
            if not has_subdirs:
                error_msg = f"No subdirectories found in music directory: {music_dir}"
                self.log_status(error_msg)
                self.log_discovery_output(f"ERROR: {error_msg}")
                self.discovery_status.setText("Error: No artist folders")
                self.discovery_button.setEnabled(True)
                self.spotify_button.setEnabled(True)
                
                # Show error message to user
                error_dialog = QMessageBox(self)
                error_dialog.setWindowTitle("No Artist Folders Found")
                error_dialog.setText("No artist folders were found in your music directory.\n\n" +
                                    "This application requires your music to be organized in artist folders (subdirectories).\n\n" +
                                    "Please organize your music into artist folders before running Music Discovery.")
                error_dialog.setIcon(QMessageBox.Warning)
                self.apply_dark_style_to_message_box(error_dialog)
                error_dialog.exec_()
                
                # Set flag to show options dialog on next button press
                self.last_button_clicked = 'discovery_error'
                return
        except Exception as e:
            error_msg = f"Error checking subdirectories: {str(e)}"
            self.log_status(error_msg)
            self.log_discovery_output(f"ERROR: {error_msg}")
            self.discovery_status.setText("Error checking folders")
            self.discovery_button.setEnabled(True)
            self.spotify_button.setEnabled(True)
            return

        # Find the script
        script_path = self.find_script("musicdiscovery.py")
        if not script_path:
            self.log_status("ERROR: Could not find musicdiscovery.py!")
            self.discovery_button.setEnabled(True)
            self.spotify_button.setEnabled(True)  # Re-enable Spotify button
            self.discovery_status.setText("Error: Script not found")
            return

        self.log_status(f"Found script at: {script_path}")

        try:
            # Create and start the worker thread
            self.discovery_worker = ScriptWorker(script_path, "Music Discovery")

            # Connect signals - need to ensure proper Qt connection type
            self.discovery_worker.update_progress.connect(self.update_discovery_progress, Qt.QueuedConnection)
            self.discovery_worker.script_finished.connect(self.discovery_finished, Qt.QueuedConnection)
            self.discovery_worker.output_text.connect(self.log_status, Qt.QueuedConnection)
            self.discovery_worker.console_output.connect(self.log_discovery_output, Qt.QueuedConnection)

            # Add arguments for music directory and to save recommendations in music directory
            self.discovery_worker.extra_args = ["--dir", music_dir, "--save-in-music-dir"]

            # Log before starting the thread
            self.log_status("Music Discovery thread created, starting...")
            self.log_discovery_output(f"Starting Music Discovery process for directory: {music_dir}...")

            # Start the thread
            self.discovery_worker.start()

            # Verify thread started
            if not self.discovery_worker.isRunning():
                raise RuntimeError("Failed to start worker thread")

            self.log_status("Music Discovery thread started successfully")
            
        except Exception as e:
            error_msg = f"Error launching Music Discovery: {str(e)}\n{traceback.format_exc()}"
            self.log_status(error_msg)
            self.log_discovery_output(f"ERROR: {str(e)}")
            
            # Re-enable buttons on error
            self.discovery_button.setEnabled(True)
            self.spotify_button.setEnabled(True)
            self.discovery_status.setText("Error starting process")

    def show_options_dialog(self):
        """Show the Options dialog with music directory and view settings."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Options")
        dialog.setMinimumWidth(500)
        
        # Create layout
        layout = QVBoxLayout()
        dialog.setLayout(layout)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Music Directory section
        music_dir_layout = QHBoxLayout()
        
        # Create label
        music_dir_label = QLabel("Music Directory:")
        music_dir_layout.addWidget(music_dir_label)
        
        # Create text field with current value
        music_dir_input = QLineEdit()
        current_dir = self.get_configured_music_dir()
        music_dir_input.setText(current_dir)  # Use current value
        music_dir_layout.addWidget(music_dir_input)
        
        # Create browse button
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(lambda: self.browse_music_dir(music_dir_input))
        music_dir_layout.addWidget(browse_button)
        
        layout.addLayout(music_dir_layout)
        
        # View Options section
        view_options_group = QGroupBox("View Options")
        view_options_layout = QVBoxLayout()
        
        # Debug Tab Toggle using custom toggle switch
        debug_toggle_layout = QHBoxLayout()
        debug_label = QLabel("Show Debug Tab")
        debug_toggle = ToggleSwitch()
        debug_toggle.setChecked(self.toggle_debug_action.isChecked())
        debug_toggle_layout.addWidget(debug_label)
        debug_toggle_layout.addStretch()
        debug_toggle_layout.addWidget(debug_toggle)
        view_options_layout.addLayout(debug_toggle_layout)
        
        # Console Output Toggle using custom toggle switch
        console_toggle_layout = QHBoxLayout()
        console_label = QLabel("Show Console Output")
        console_toggle = ToggleSwitch()
        console_toggle.setChecked(self.toggle_console_action.isChecked())
        console_toggle_layout.addWidget(console_label)
        console_toggle_layout.addStretch()
        console_toggle_layout.addWidget(console_toggle)
        view_options_layout.addLayout(console_toggle_layout)
        
        view_options_group.setLayout(view_options_layout)
        layout.addWidget(view_options_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)
        layout.addLayout(button_layout)
        
        # Button connections
        cancel_button.clicked.connect(dialog.reject)
        save_button.clicked.connect(lambda: self.save_options(dialog, music_dir_input.text(), 
                                                             debug_toggle.isChecked(), 
                                                             console_toggle.isChecked()))
        
        # Apply dark theme styling
        dark_bg = "#121212"           # Dark background
        dark_accent = "#1F1F1F"       # Slightly lighter accent
        text_color = "#E0E0E0"        # Light text color
        spotify_green = "#1DB954"     # Spotify green
        border_color = "#333333"      # Border color
        
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {dark_bg};
                color: {text_color};
            }}
            QLabel, QCheckBox {{
                color: {text_color};
            }}
            QLineEdit {{
                background-color: {dark_accent};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 8px;
            }}
            QPushButton {{
                background-color: {spotify_green};
                color: white;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #1ED760;
            }}
            QPushButton:pressed {{
                background-color: #169C46;
            }}
            QGroupBox {{
                color: {text_color};
                border: 1px solid {border_color};
                margin-top: 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }}
        """)
        
        # Apply dark title bar using Windows API (for Windows only)
        try:
            if sys.platform == 'win32':
                # Define Windows API constants
                DWMWA_CAPTION_COLOR = 35  # DWM caption color attribute
                DWMWA_TEXT_COLOR = 36     # DWM caption text color attribute
                
                # Dark title bar color (#121212) in COLORREF format
                dark_title_color = 0x00121212
                
                # Light text color (white #FFFFFF) in COLORREF format
                light_text_color = 0x00FFFFFF
                
                # Get the window handle
                hWnd = dialog.winId()
                
                # Apply the dark color to the title bar
                windll.dwmapi.DwmSetWindowAttribute(
                    int(hWnd),
                    DWMWA_CAPTION_COLOR,
                    byref(c_int(dark_title_color)),
                    sizeof(c_int)
                )
                
                # Apply the light text color to the title bar
                windll.dwmapi.DwmSetWindowAttribute(
                    int(hWnd),
                    DWMWA_TEXT_COLOR,
                    byref(c_int(light_text_color)),
                    sizeof(c_int)
                )
        except Exception as e:
            print(f"Error setting title bar color for options dialog: {e}")
        
        # Show the dialog
        dialog.exec_()
    
    def save_options(self, dialog, music_dir, debug_tab_enabled, console_output_enabled):
        """
        Save options from the Options dialog.
        
        Args:
            dialog (QDialog): The dialog to close
            music_dir (str): Selected music directory
            debug_tab_enabled (bool): Whether debug tab is enabled
            console_output_enabled (bool): Whether console output is enabled
        """
        # Validate directory exists
        if not os.path.isdir(music_dir):
            error_dialog = QMessageBox(self)
            error_dialog.setWindowTitle("Invalid Directory")
            error_dialog.setText("The specified directory does not exist. Please enter a valid path.")
            error_dialog.setIcon(QMessageBox.Warning)
            self.apply_dark_style_to_message_box(error_dialog)
            error_dialog.exec_()
            return

        # Normalize to use backslashes (Windows-style)
        normalized_music_dir = music_dir.replace('/', '\\')

        # Save the directory path to a config file
        config_path = os.path.join(self.get_base_dir(), "config.json")
        config = {
            "music_directory": normalized_music_dir,
            "debug_tab_enabled": debug_tab_enabled,
            "console_output_enabled": console_output_enabled
        }

        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)

            # Update view settings
            if debug_tab_enabled != self.toggle_debug_action.isChecked():
                self.toggle_debug_action.setChecked(debug_tab_enabled)
                self.safe_toggle_debug_tab(debug_tab_enabled)

            if console_output_enabled != self.toggle_console_action.isChecked():
                self.toggle_console_action.setChecked(console_output_enabled)
                self.safe_toggle_console_output(console_output_enabled)

            # Close the dialog
            dialog.accept()

            # Resume appropriate operation
            if self.last_button_clicked == 'discovery':
                self.log_status("Resuming Music Discovery operation after configuration")
                self.run_music_discovery()
            elif self.last_button_clicked == 'spotify':
                self.log_status("Resuming Spotify Client operation after configuration")
                self.run_spotify_client()
            else:
                # Show confirmation
                confirm_dialog = QMessageBox(self)
                confirm_dialog.setWindowTitle("Options Saved")
                confirm_dialog.setText("Options have been successfully saved.")
                confirm_dialog.setIcon(QMessageBox.Information)
                self.apply_dark_style_to_message_box(confirm_dialog)
                confirm_dialog.exec_()

        except Exception as e:
            error_dialog = QMessageBox(self)
            error_dialog.setWindowTitle("Error")
            error_dialog.setText(f"Could not save configuration: {str(e)}")
            error_dialog.setIcon(QMessageBox.Critical)
            self.apply_dark_style_to_message_box(error_dialog)
            error_dialog.exec_()


    def setup_menu(self):
        """Set up the menu bar with options."""
        menubar = self.menuBar()
        
        # Settings menu 
        settings_menu = menubar.addMenu('Settings')
        
        # Options action to open dialog with multiple settings
        options_action = QAction('Options', self)
        options_action.triggered.connect(self.show_options_dialog)
        settings_menu.addAction(options_action)
        
        # Help menu
        help_menu = menubar.addMenu('Help')
        
        # About action
        about_action = QAction('About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        # View GPL3 Licence direct link
        view_gpl_action = QAction('View GPL3 Licence', self)
        view_gpl_action.triggered.connect(lambda: webbrowser.open('https://www.gnu.org/licenses/gpl-3.0.html'))
        help_menu.addAction(view_gpl_action)

    def safe_toggle_debug_tab(self, checked):
        """
        Safely toggle the debug tab with error handling.
        
        Args:
            checked (bool): Whether debug tab should be visible
        """
        try:
            # Check if any processes are running
            processes_running = False
            if hasattr(self, 'discovery_worker') and self.discovery_worker and self.discovery_worker.isRunning():
                processes_running = True
            if hasattr(self, 'spotify_worker') and self.spotify_worker and self.spotify_worker.isRunning():
                processes_running = True
            
            # If processes are running, show a warning dialog
            if processes_running:
                # Create custom error dialog
                error_dialog = QMessageBox(self)
                error_dialog.setWindowTitle("Cannot Change View")
                error_dialog.setText("Cannot change console visibility while processes are running.\n" +
                                     "Please wait for the current operation to complete.")
                error_dialog.setIcon(QMessageBox.Warning)
                
                # Apply dark theme styling to the dialog
                self.apply_dark_style_to_message_box(error_dialog)
                
                # Show the dialog
                error_dialog.exec_()
                
                # Restore the action state to match the current visibility
                current_visible = self.output_tabs.indexOf(self.debug_output) != -1
                self.toggle_debug_action.blockSignals(True)
                self.toggle_debug_action.setChecked(current_visible)
                self.toggle_debug_action.blockSignals(False)
                return
            
            # Proceed with toggling if no processes are running
            self.toggle_debug_tab(checked)
            
        except Exception as e:
            # If any exception occurs during toggling
            self.log_status(f"Error toggling debug tab: {str(e)}")
            
            # Create custom error dialog
            error_dialog = QMessageBox(self)
            error_dialog.setWindowTitle("View Error")
            error_dialog.setText(f"An error occurred while changing the view: {str(e)}")
            error_dialog.setIcon(QMessageBox.Warning)
            
            # Apply dark theme styling to the dialog
            self.apply_dark_style_to_message_box(error_dialog)
            
            # Show the dialog
            error_dialog.exec_()
            
            # Attempt to restore the action state
            current_visible = self.output_tabs.indexOf(self.debug_output) != -1
            self.toggle_debug_action.blockSignals(True)
            self.toggle_debug_action.setChecked(current_visible)
            self.toggle_debug_action.blockSignals(False)

    def safe_toggle_console_output(self, checked):
        """
        Safely toggle the console output with error handling.
        
        Args:
            checked (bool): Whether console output should be visible
        """
        try:
            # Check if any processes are running
            processes_running = False
            if hasattr(self, 'discovery_worker') and self.discovery_worker and self.discovery_worker.isRunning():
                processes_running = True
            if hasattr(self, 'spotify_worker') and self.spotify_worker and self.spotify_worker.isRunning():
                processes_running = True
            
            # If processes are running, show a warning dialog
            if processes_running:
                # Create custom error dialog
                error_dialog = QMessageBox(self)
                error_dialog.setWindowTitle("Cannot Change View")
                error_dialog.setText("Cannot change console visibility while processes are running.\n" +
                                     "Please wait for the current operation to complete.")
                error_dialog.setIcon(QMessageBox.Warning)
                
                # Apply dark theme styling to the dialog
                self.apply_dark_style_to_message_box(error_dialog)
                
                # Show the dialog
                error_dialog.exec_()
                
                # Restore the action state to match the current visibility
                current_visible = self.output_tabs.isVisible()
                self.toggle_console_action.blockSignals(True)
                self.toggle_console_action.setChecked(current_visible)
                self.toggle_console_action.blockSignals(False)
                return
            
            # Proceed with toggling if no processes are running
            self.toggle_console_output(checked)
            
        except Exception as e:
            # If any exception occurs during toggling
            self.log_status(f"Error toggling console output: {str(e)}")
            
            # Create custom error dialog
            error_dialog = QMessageBox(self)
            error_dialog.setWindowTitle("View Error")
            error_dialog.setText(f"An error occurred while changing the view: {str(e)}")
            error_dialog.setIcon(QMessageBox.Warning)
            
            # Apply dark theme styling to the dialog
            self.apply_dark_style_to_message_box(error_dialog)
            
            # Show the dialog
            error_dialog.exec_()
            
            # Attempt to restore the action state
            current_visible = self.output_tabs.isVisible()
            self.toggle_console_action.blockSignals(True)
            self.toggle_console_action.setChecked(current_visible)
            self.toggle_console_action.blockSignals(False)

    def toggle_debug_tab(self, checked):
        """
        Toggle the visibility of the debug tab.
        
        Args:
            checked (bool): Whether to show the debug tab
        """
        # Check if any processes are running
        processes_running = False
        if hasattr(self, 'discovery_worker') and self.discovery_worker and self.discovery_worker.isRunning():
            processes_running = True
        if hasattr(self, 'spotify_worker') and self.spotify_worker and self.spotify_worker.isRunning():
            processes_running = True
        
        # If processes are running, show a warning and abort the toggle
        if processes_running:
            QMessageBox.warning(self, "Cannot Change View", 
                                "Cannot change debug tab visibility while processes are running.\n"
                                "Please wait for the current operation to complete.")
            # Restore the action state to match the current visibility
            current_visible = self.output_tabs.indexOf(self.debug_output) != -1
            self.toggle_debug_action.setChecked(current_visible)
            return
        
        # The tab is always there, we just need to handle showing/hiding it
        if checked:
            if self.output_tabs.indexOf(self.debug_output) == -1:
                # Add a bug symbol 🐞 to the debug tab title
                self.output_tabs.addTab(self.debug_output, "🐞 Debug Log")
        else:
            idx = self.output_tabs.indexOf(self.debug_output)
            if idx >= 0:
                self.output_tabs.removeTab(idx)
    
    def load_settings(self):
        """Load and apply saved settings from config file."""
        config_path = os.path.join(self.get_base_dir(), "config.json")
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    
                    # Apply debug tab setting
                    debug_tab_enabled = config.get("debug_tab_enabled", False)
                    self.toggle_debug_action.setChecked(debug_tab_enabled)
                    self.toggle_debug_tab(debug_tab_enabled)
                    self.log_status(f"Debug tab enabled: {debug_tab_enabled}")
                    
                    # Apply console output setting
                    console_output_enabled = config.get("console_output_enabled", False)
                    self.toggle_console_action.setChecked(console_output_enabled)
                    self.toggle_console_output(console_output_enabled)
                    self.log_status(f"Console output enabled: {console_output_enabled}")
                    
                    # Log the loaded music directory
                    music_dir = config.get("music_directory", "")
                    if music_dir and os.path.isdir(music_dir):
                        self.log_status(f"Loaded music directory: {music_dir}")
            else:
                self.log_status("No config file found, using default settings")
                # Set default values - no console output and no debug tab on first launch
                self.toggle_debug_action.setChecked(False)
                self.toggle_debug_tab(False)
                self.toggle_console_action.setChecked(False)
                self.toggle_console_output(False)
                    
        except Exception as e:
            self.log_status(f"Error loading settings: {str(e)}")
            # Fallback to defaults on error - no console output and no debug tab
            self.toggle_debug_action.setChecked(False)
            self.toggle_debug_tab(False)
            self.toggle_console_action.setChecked(False)
            self.toggle_console_output(False)  
    
    def toggle_console_output(self, checked):
        """
        Toggle the visibility of the console output tabs.
        
        Args:
            checked (bool): Whether console output should be visible
        """
        # Check if any processes are running
        processes_running = False
        if hasattr(self, 'discovery_worker') and self.discovery_worker and self.discovery_worker.isRunning():
            processes_running = True
        if hasattr(self, 'spotify_worker') and self.spotify_worker and self.spotify_worker.isRunning():
            processes_running = True
        
        # If processes are running, show a warning and abort the toggle
        if processes_running:
            QMessageBox.warning(self, "Cannot Change View", 
                                "Cannot change console visibility while processes are running.\n"
                                "Please wait for the current operation to complete.")
            # Restore the action state to match the current visibility
            self.toggle_console_action.setChecked(self.output_tabs.isVisible())
            return
        
        # Toggle visibility of console output
        self.output_tabs.setVisible(checked)
        
        # Toggle visibility of text labels
        self.spotify_status1.setVisible(checked)
        self.spotify_status2.setVisible(checked)
        self.discovery_status.setVisible(checked)
        self.spotify_phase1_label.setVisible(checked)
        self.spotify_phase2_label.setVisible(checked)
        
        # The central widget layout and upper widget layout
        main_layout = self.central_widget.layout()
        
        # Only adjust spacing if layouts exist
        if main_layout:
            if not checked:
                # When hiding console, set compact layout
                main_layout.setSpacing(5)
                # Set fixed height for window in compact mode
                self.setFixedHeight(350)  # Compact height based on screenshots
            else:
                # When showing console, restore original spacing
                main_layout.setSpacing(15)
                # Remove fixed height constraint
                self.setFixedHeight(QWIDGETSIZE_MAX)  # Remove height constraint
                # Restore to a reasonable size when showing console
                self.resize(self.width(), 700)
        
        # Force layout update
        QApplication.processEvents()
        
    def show_about(self):
        """Show information about the application with dark theme styling."""
        about_text = """
    GenreGenius - Version 1.1.0
    By Oliver Ernster

    A tool for discovering music and generating
    Spotify playlists by genre.

    Licensed under GPL-3.0
    Copyright © 2025 Oliver Ernster
        """
        
        # Create message box
        about_dialog = QMessageBox()
        about_dialog.setWindowTitle("About Playlist Generator")
        about_dialog.setText(about_text)
        
        # Try to set the icon
        try:
            # Try ICO first
            icon_path = os.path.join(self.get_base_dir(), "genregenius.ico")
            
            if os.path.exists(icon_path):
                # Create QIcon from the icon file
                app_icon = QIcon(icon_path)
                
                # Set both the dialog icon and pixmap
                about_dialog.setWindowIcon(app_icon)
                
                # For the large icon in the dialog content, use the 64x64 size explicitly
                pixmap = app_icon.pixmap(64, 64)
                about_dialog.setIconPixmap(pixmap)
        except Exception as e:
            self.log_status(f"Error setting about dialog icon: {str(e)}")
        
        # Apply dark theme styling to the dialog
        self.apply_dark_style_to_message_box(about_dialog)
        
        # Show the dialog
        about_dialog.exec_()

    def load_set_icon(self):
        """Load and set the application icon."""
        try:
            # Try to find the ICO file first
            icon_path = os.path.join(self.get_base_dir(), "genregenius.ico")
            
            if os.path.exists(icon_path):
                self.log_status(f"Loading icon from: {icon_path}")
                app_icon = QIcon(icon_path)
                self.setWindowIcon(app_icon)
                self.log_status("Icon loaded successfully")
            else:
                self.log_status("No icon file found")
        except Exception as e:
            self.log_status(f"Error loading icon: {str(e)}")

    def get_base_dir(self) -> str:
        """
        Get the directory where the executable is located.
        
        Returns:
            str: Base directory path
        """
        if getattr(sys, 'frozen', False):
            # We're running in a bundle (PyInstaller)
            return os.path.dirname(sys.executable)
        else:
            # We're running in a normal Python environment
            return os.path.dirname(os.path.abspath(__file__)) or os.getcwd()

    def find_script(self, script_name: str) -> Optional[str]:
        """
        Find a script in various possible locations.
        
        Args:
            script_name (str): Name of the script file
            
        Returns:
            Optional[str]: Path to the script or None if not found
        """
        base_dir = self.get_base_dir()
        
        # List of possible locations to check
        possible_locations = [
            os.path.join(base_dir, script_name),                 # Same directory as executable
            os.path.join(base_dir, "_internal", script_name),    # _internal directory for PyInstaller onefile
            os.path.join(os.path.dirname(base_dir), script_name), # Parent directory
            os.path.join(os.getcwd(), script_name)               # Current working directory
        ]
        
        for location in possible_locations:
            self.log_status(f"Checking for script at: {location}")
            if os.path.exists(location):
                self.log_status(f"Found script at: {location}")
                return location
                
        self.log_status(f"Script not found: {script_name}")
        return None

    def log_status(self, message: str):
        """
        Thread-safe logging to add a message to the debug output.
        
        Args:
            message (str): Message to log
        """
        try:
            # Always print to console as a backup
            print(f"DEBUG: {message}")
            
            # Direct approach when in the main thread
            if QThread.currentThread() == QApplication.instance().thread():
                if hasattr(self, 'debug_output') and self.debug_output is not None:
                    timestamp = time.strftime("%H:%M:%S", time.localtime())
                    formatted_message = f"[{timestamp}] {message}"
                    self.debug_output.append(formatted_message)
                    self.debug_output.ensureCursorVisible()
            else:
                # Use the logger when in a worker thread
                if hasattr(self, 'logger') and self.logger is not None and hasattr(self, 'debug_output'):
                    self.logger.log_debug(message, self.debug_output)
                elif hasattr(self, 'debug_output') and self.debug_output is not None:
                    # Fallback using signals/slots
                    QMetaObject.invokeMethod(
                        self.debug_output,
                        "append",
                        Qt.QueuedConnection,
                        QArgument("QString", f"[{time.strftime('%H:%M:%S', time.localtime())}] {message}")
                    )
                    QMetaObject.invokeMethod(
                        self.debug_output,
                        "ensureCursorVisible",
                        Qt.QueuedConnection
                    )
        except Exception as e:
            # Last resort fallback
            print(f"Error in log_status: {e} - Message was: {message}")

    def log_discovery_output(self, message: str):
        """
        Thread-safe logging to add a message to the Music Discovery output.
        
        Args:
            message (str): Message to log
        """
        try:
            # Direct approach when in the main thread
            if QThread.currentThread() == QApplication.instance().thread():
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                formatted_message = f"[{timestamp}] {message}"
                self.discovery_output.append(formatted_message)
                self.discovery_output.ensureCursorVisible()
                
                # Also update status label if it's a meaningful status message
                if len(message) > 3 and not message.startswith("Executing:") and not message.startswith("Working directory:"):
                    self.discovery_status.setText(self.truncate_status(message))
            else:
                # Use the logger when in a worker thread
                if hasattr(self, 'logger') and self.logger is not None:
                    self.logger.log_discovery(message, self.discovery_output, self.discovery_status)
                else:
                    # Fallback using signals/slots
                    print(f"Logging from thread: {message}")
                    # Use invokeMethod directly as fallback
                    QMetaObject.invokeMethod(
                        self.discovery_output,
                        "append",
                        Qt.QueuedConnection,
                        QArgument("QString", f"[{time.strftime('%H:%M:%S', time.localtime())}] {message}")
                    )
                    QMetaObject.invokeMethod(
                        self.discovery_output,
                        "ensureCursorVisible",
                        Qt.QueuedConnection
                    )
        except Exception as e:
            # Last resort fallback
            print(f"Error in log_discovery_output: {e} - Message was: {message}")

    def log_spotify_output(self, message: str):
        """
        Thread-safe logging to add a message to the Spotify Client output.
        
        Args:
            message (str): Message to log
        """
        try:
            # Direct approach when in the main thread
            if QThread.currentThread() == QApplication.instance().thread():
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                formatted_message = f"[{timestamp}] {message}"
                self.spotify_output.append(formatted_message)
                self.spotify_output.ensureCursorVisible()
                
                # Update appropriate status label
                status_label = self.spotify_status2 if self.phase2_active else self.spotify_status1
                status_label.setText(self.truncate_status(message))
            else:
                # Use the logger when in a worker thread
                if hasattr(self, 'logger') and self.logger is not None:
                    status_label = self.spotify_status2 if self.phase2_active else self.spotify_status1
                    self.logger.log_spotify(message, self.spotify_output, status_label)
                else:
                    # Fallback using signals/slots
                    print(f"Spotify logging from thread: {message}")
                    # Use invokeMethod directly as fallback
                    QMetaObject.invokeMethod(
                        self.spotify_output,
                        "append",
                        Qt.QueuedConnection,
                        QArgument("QString", f"[{time.strftime('%H:%M:%S', time.localtime())}] {message}")
                    )
                    QMetaObject.invokeMethod(
                        self.spotify_output,
                        "ensureCursorVisible",
                        Qt.QueuedConnection
                    )
        except Exception as e:
            # Last resort fallback
            print(f"Error in log_spotify_output: {e} - Message was: {message}")
          
    def get_configured_music_dir(self):
        """Get the configured music directory from config file or use default."""
        config_path = os.path.join(self.get_base_dir(), "config.json")
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    music_dir = config.get("music_directory")
                    if music_dir and os.path.isdir(music_dir):
                        self.log_status(f"Using configured music directory: {music_dir}")
                        return music_dir
        except Exception as e:
            self.log_status(f"Error reading config: {str(e)}")
        
        # Default fallback - use user's music folder
        try:
            # Get the user's home directory
            home_dir = os.path.expanduser("~")
            # Standard "Music" folder in user's profile
            default_dir = os.path.join(home_dir, "Music")
            
            # Check if the Music folder exists
            if os.path.isdir(default_dir):
                self.log_status(f"Using user's Music directory: {default_dir}")
                return default_dir
                
            # If Music folder doesn't exist, use Documents as fallback
            docs_dir = os.path.join(home_dir, "Documents")
            if os.path.isdir(docs_dir):
                self.log_status(f"Music folder not found, using Documents directory: {docs_dir}")
                return docs_dir
                
            # Final fallback to home directory
            self.log_status(f"Using user's home directory: {home_dir}")
            return home_dir
                
        except Exception as e:
            self.log_status(f"Error finding default music directory: {str(e)}")
            # Absolute last resort fallback
            fallback_dir = "C:\\Music"
            self.log_status(f"Using fallback music directory: {fallback_dir}")
            return fallback_dir
          
    def launch_music_discovery(self):
        """Launch the Music Discovery script with progress tracking."""
        # If we had a previous error about missing artist folders or invalid directory,
        # immediately show the options dialog on next button press
        if self.last_button_clicked == 'discovery_error':
            self.log_status("Previous error detected, showing options dialog")
            self.last_button_clicked = 'discovery'  # Set to normal discovery mode
            self.show_options_dialog()
            return
        
        # Set the last button clicked
        self.last_button_clicked = 'discovery'
        
        # Check if configuration exists
        if not self.is_configuration_valid():
            self.log_status("No valid configuration found. Showing options dialog.")
            self.show_options_dialog()
            return
        
        # Clear the last button clicked as we're proceeding normally
        self.last_button_clicked = None
        
        # Run the actual process
        self.run_music_discovery()

    def discovery_finished(self, success: bool):
        """
        Handle when music discovery is finished.
        
        Args:
            success (bool): Whether the script completed successfully
        """
        self.discovery_button.setEnabled(True)
        
        # Re-enable the Spotify button when Music Discovery completes
        self.spotify_button.setEnabled(True)
        
        if success:
            # Check for completion message in the output
            completion_detected = False
            cancellation_detected = False
            
            if hasattr(self, 'discovery_output'):
                output_text = self.discovery_output.toPlainText().lower()
                
                # Check for successful completion
                completion_detected = any(phrase in output_text for phrase in [
                    "music discovery complete",
                    "process finished with return code: 0",
                    "completed successfully",
                    "check", "recommendations.json"  # Look for the output file reference
                ])
                
                # Check specifically for cancellation messages
                cancellation_detected = any(phrase in output_text for phrase in [
                    "no directory selected",
                    "no file selected",
                    "operation cancelled"
                ])
                
                # Also check if the output is very short (suggesting the file dialog was just opened and closed)
                if len(output_text.split()) < 10 and "executing:" in output_text:
                    cancellation_detected = True
            
            # Check if the progress is very low (suggesting we barely started)
            if self.discovery_progress.value() < 5:
                cancellation_detected = True
            
            # ONLY mark as complete if we detect explicit completion indicators
            if completion_detected and not cancellation_detected:
                # Real completion - set to 100%
                self.discovery_progress.setValue(100)
                self.discovery_status.setText("Completed successfully")
                self.log_discovery_output("Music Discovery completed successfully.")
            else:
                # Either explicit cancellation or no proper completion detected
                self.discovery_progress.setValue(0)
                self.discovery_status.setText("Ready")
                
                if cancellation_detected:
                    self.log_discovery_output("Operation cancelled.")
                else:
                    self.log_discovery_output("Process did not complete successfully.")
        else:
            # Reset on failure
            self.discovery_progress.setValue(0)
            self.discovery_status.setText("Failed")
            self.log_discovery_output("Music Discovery process failed.")

    def launch_spotify_client(self):
        """Launch the Spotify Client script with progress tracking."""
        # Set the last button clicked
        self.last_button_clicked = 'spotify'
        
        # Check if configuration exists
        if not self.is_configuration_valid():
            self.log_status("No valid configuration found. Showing options dialog.")
            self.show_options_dialog()
            return
        
        # Clear the last button clicked as we're proceeding normally
        self.last_button_clicked = None
        
        # Run the actual process
        self.run_spotify_client()
           
    def update_spotify_progress(self, value: int, status: str):
        """
        Update the appropriate progress bar based on the phase.
        
        Args:
            value (int): Progress value (0-100), or special codes for different status updates
            status (str): Status message
        """
        try:
            # Log all progress updates for debugging
            self.log_status(f"Spotify progress update received: value={value}, status={status}")
            
            # Special status update codes:
            # -1: Phase 1 complete
            # -2: Phase transition
            # -3: Processing artist
            # -4: Creating playlist
            # -5: Playlist created
            # -6: Processing genre
            # -7: Finding tracks for artist
            
            # Handle phase transition with special code -2
            if value == -2 or any(marker in status.lower() for marker in [
                "starting playlist generation",
                "processing genres", 
                "processing artists in genre",
                "generating playlist",
                "creating playlist"
            ]):
                # Mark Phase 1 as complete (but don't change its current progress)
                # Only do this once when transitioning
                if not self.phase2_active:
                    self.spotify_status1.setText("Artist Classification Complete")
                    # Initialize Phase 2
                    self.phase2_active = True
                    self.spotify_progress2.setValue(0)
                    self.spotify_status2.setText("Starting Playlist Generation")
                return
            
            # Handle phase 1 completion signal with special code -1
            if value == -1 and not self.phase2_active:
                # Don't change the progress bar, just update the status text
                self.spotify_status1.setText("Artist Classification Complete")
                return
            
            # Check if we're in phase 2 for genre/artist specific updates
            if self.phase2_active:
                # Genre processing update (code -6)
                if value == -6:
                    self.spotify_status2.setText(self.truncate_status(status))
                    return
                    
                # Finding tracks for artist (code -7)
                if value == -7:
                    self.spotify_status2.setText(self.truncate_status(status))
                    return
                    
                # Creating playlist (code -4)
                if value == -4:
                    self.spotify_status2.setText(self.truncate_status(status))
                    return
                    
                # Playlist created successfully (code -5)
                if value == -5:
                    self.spotify_status2.setText(self.truncate_status(status))
                    return
                    
                # Processing artist (code -3)
                if value == -3:
                    self.spotify_status2.setText(self.truncate_status(status))
                    return
                    
                # Direct progress update for phase 2
                if 0 <= value <= 100:
                    self.spotify_progress2.setValue(value)
                    self.spotify_status2.setText(self.truncate_status(status))
                    return
            
            # Advanced artist processing pattern matching - for Phase 1
            artist_match = re.search(r'Processing: (\d+\.\d+)% \((\d+)/(\d+) artists\)', status)
            if artist_match and not self.phase2_active:
                percentage = float(artist_match.group(1))
                current = int(artist_match.group(2))
                total = int(artist_match.group(3))
                
                # Set progress bar for Phase 1
                self.spotify_progress1.setValue(int(percentage))
                
                # Detailed status with artist count
                status_text = f"Processing artist {current} of {total}"
                self.spotify_status1.setText(self.truncate_status(status_text))
                
                # Log the progress for debugging
                self.log_status(f"Updated Phase 1 progress bar to {percentage}% ({current}/{total})")
                return
            
            # Check for "Genres: X/Y (Z%) - Artists: A/B" format for Phase 2
            genres_artists_match = re.search(r'Genres: (\d+)/(\d+) \((\d+)%\) - Artists: (\d+)/(\d+)', status)
            if genres_artists_match and self.phase2_active:
                current_genre = int(genres_artists_match.group(1))
                total_genres = int(genres_artists_match.group(2))
                percentage = int(genres_artists_match.group(3))
                current_artist = int(genres_artists_match.group(4))
                total_artists = int(genres_artists_match.group(5))
                
                # Update progress bar for Phase 2
                self.spotify_progress2.setValue(percentage)
                
                # Detailed status showing both genre and artist progress
                status_text = f"Genres: {current_genre}/{total_genres} - Artists: {current_artist}/{total_artists}"
                self.spotify_status2.setText(self.truncate_status(status_text))
                
                # Log the progress for debugging
                self.log_status(f"Updated Phase 2 progress bar to {percentage}% - {status_text}")
                return
            
            # Check for "Genre X: Y/Z artists - Overall: A/B artists" format for Phase 2
            genre_artists_match = re.search(r'Genre (.+?): (\d+)/(\d+) artists - Overall: (\d+)/(\d+) artists', status)
            if genre_artists_match and self.phase2_active:
                genre_name = genre_artists_match.group(1)
                current_in_genre = int(genre_artists_match.group(2))
                total_in_genre = int(genre_artists_match.group(3))
                overall_current = int(genre_artists_match.group(4))
                overall_total = int(genre_artists_match.group(5))
                
                # Calculate percentage based on overall artists
                if overall_total > 0:
                    percentage = int((overall_current / overall_total) * 100)
                    self.spotify_progress2.setValue(percentage)
                
                # Detailed status showing both current genre and overall progress
                status_text = f"Genre {genre_name}: {current_in_genre}/{total_in_genre} - Overall: {overall_current}/{overall_total}"
                self.spotify_status2.setText(self.truncate_status(status_text))
                
                # Log the progress for debugging
                self.log_status(f"Updated Phase 2 progress bar for genre processing - {status_text}")
                return
            
            # Fall back to direct progress percentage update if we're in the appropriate phase
            if 0 <= value <= 100:
                if self.phase2_active:
                    self.spotify_progress2.setValue(value)
                    
                    # If this is a completion signal
                    if value >= 95:
                        self.spotify_status2.setText("Completing playlist generation...")
                else:
                    self.spotify_progress1.setValue(value)
            
            # Regular status updates - determine which phase to update
            if self.phase2_active:
                # Only update status text for meaningful messages
                if not any(skip in status.lower() for skip in [
                    "found virtual environment", 
                    "spotify authentication", 
                    "executing:", 
                    "working directory:",
                    "found artist progress:",
                    "progress: ",  # Ignore raw progress messages
                    "pausing for"   # Ignore rate limit pausing messages
                ]):
                    self.spotify_status2.setText(self.truncate_status(status))
            else:
                # Only update status text for Phase 1 if not a progress percentage update
                if not any(skip in status.lower() for skip in [
                    "found virtual environment", 
                    "spotify authentication", 
                    "executing:", 
                    "working directory:",
                    "found artist progress:",
                    "progress: ",  # Ignore raw progress messages
                    "pausing for"  # Ignore rate limit pausing messages
                ]):
                    self.spotify_status1.setText(self.truncate_status(status))
        
        except Exception as e:
            # Log the error but don't crash
            error_msg = f"Error in update_spotify_progress: {str(e)}\n{traceback.format_exc()}"
            self.log_status(error_msg)
            print(f"Error in update_spotify_progress: {str(e)}")
            
    def update_discovery_progress(self, value: int, status: str):
        """
        Update discovery progress with improved status display.
        
        Args:
            value (int): Progress value
            status (str): Status message
        """
        try:
            # Log all progress updates for debugging
            self.log_status(f"Progress update received: value={value}, status={status}")
            
            # IGNORE all directory-based progress that only has numbers
            if "directories" in status and re.search(r'directories\)$', status):
                self.log_status("Ignoring directory progress")
                return
            
            # Special status update codes:
            # -1: Phase complete
            # -2: Phase transition
            # -3: Processing artist
            # -4: Creating playlist
            # -5: Playlist created
            # -6: Processing genre
            # -7: Finding tracks for artist
            
            # Handle special status codes
            if value < 0:
                # Don't update progress bar for these special status updates
                if status and len(status) > 3:
                    self.discovery_status.setText(self.truncate_status(status))
                return
            
            # Advanced artist processing pattern matching
            artist_match = re.search(r'Processing: (\d+)/(\d+) artists', status)

            if artist_match:
                current = int(artist_match.group(1))
                total = int(artist_match.group(2))
                
                # Set progress bar
                self.discovery_progress.setValue(value)
                
                # Detailed status with artist count
                status_text = f"Processing artist {current} of {total}"
                self.discovery_status.setText(status_text)
            
            # Progress percentage update (from the value parameter)
            if isinstance(value, int) and value >= 0 and value <= 100:
                self.discovery_progress.setValue(value)
                self.log_status(f"Set progress to {value}% from value parameter")
        
        except Exception as e:
            # Log the error but don't crash
            error_msg = f"Error in update_discovery_progress: {str(e)}\n{traceback.format_exc()}"
            self.log_status(error_msg)
            print(error_msg)

    def throttle_status_update(self, phase: str, status: str, label) -> bool:
        """
        Throttle status updates to prevent rapid flickering.
        
        Args:
            phase (str): Phase identifier ('discovery', 'spotify_phase1', 'spotify_phase2')
            status (str): Status message to potentially update
            label (QLabel): Label to update
            
        Returns:
            bool: Whether the update should proceed
        """
        current_time = time.time()
        last_update = STATUS_UPDATE_THROTTLE.get(phase, 0)
        
        # Throttle to 1 seconds between updates
        if current_time - last_update >= 1:
            STATUS_UPDATE_THROTTLE[phase] = current_time
            return True
        
        return False

    def update_spotify_progress(self, value: int, status: str):
        """
        Update the appropriate progress bar based on the phase.
        
        Args:
            value (int): Progress value (0-100), or special codes for different status updates
            status (str): Status message
        """
        try:
            # Log all progress updates for debugging
            self.log_status(f"Spotify progress update received: value={value}, status={status}")
            
            # Special status update codes:
            # -1: Phase 1 complete
            # -2: Phase transition
            # -3: Processing artist
            # -4: Creating playlist
            # -5: Playlist created
            # -6: Processing genre
            # -7: Finding tracks for artist
            
            # Handle phase transition with special code -2
            if value == -2 or any(marker in status.lower() for marker in [
                "starting playlist generation",
                "processing genres", 
                "processing artists in genre",
                "generating playlist",
                "creating playlist"
            ]):
                # Mark Phase 1 as complete (but don't change its current progress)
                # Only do this once when transitioning
                if not self.phase2_active:
                    self.spotify_status1.setText("Artist Classification Complete")
                    # Initialize Phase 2
                    self.phase2_active = True
                    self.spotify_progress2.setValue(0)
                    self.spotify_status2.setText("Starting Playlist Generation")
                return
            
            # Handle phase 1 completion signal with special code -1
            if value == -1 and not self.phase2_active:
                # Don't change the progress bar, just update the status text
                self.spotify_status1.setText("Artist Classification Complete")
                return
            
            # Advanced artist processing pattern matching
            artist_match = re.search(r'Processing: (\d+\.\d+)% \((\d+)/(\d+) artists\)', status)

            if artist_match:
                percentage = float(artist_match.group(1))
                current = int(artist_match.group(2))
                total = int(artist_match.group(3))
                
                # Set progress bar
                if not self.phase2_active:
                    self.spotify_progress1.setValue(int(percentage))
                    
                    # Detailed status with artist count
                    status_text = f"Processing artist {current} of {total}"
                    self.spotify_status1.setText(status_text)
                else:
                    self.spotify_progress2.setValue(int(percentage))
                    
                    # Detailed status with artist count
                    status_text = f"Processing artist {current} of {total} (Playlist Generation)"
                    self.spotify_status2.setText(status_text)
                    
                    # Log the progress for debugging
                    self.log_status(f"Updated Phase 2 progress bar to {percentage}% ({current}/{total})")
                
                return
            
            # Direct progress percentage update (from the value parameter)
            if 0 <= value <= 100:
                if self.phase2_active:
                    self.spotify_progress2.setValue(value)
                    # If this is a completion signal
                    if value >= 95:
                        self.spotify_status2.setText("Completing playlist generation...")
                else:
                    self.spotify_progress1.setValue(value)
        
        except Exception as e:
            # Log the error but don't crash
            error_msg = f"Error in update_spotify_progress: {str(e)}\n{traceback.format_exc()}"
            self.log_status(error_msg)
            print(f"Error in update_spotify_progress: {str(e)}")
    
    def spotify_finished(self, success: bool):
        """
        Handle when spotify client is finished.
        
        Args:
            success (bool): Whether the script completed successfully
        """
        self.spotify_button.setEnabled(True)
        
        # Re-enable the Music Discovery button when Spotify Client completes
        self.discovery_button.setEnabled(True)
        
        if success:
            # Check for completion message in the output
            completion_detected = False
            cancellation_detected = False
            
            if hasattr(self, 'spotify_output'):
                output_text = self.spotify_output.toPlainText().lower()
                
                # Check for successful completion
                completion_detected = any(phrase in output_text for phrase in [
                    "process finished with return code: 0",
                    "completed successfully",
                    "progress: 100.0%",
                    "playlist url:",      # Definitive sign of completion - playlist was created
                    "successfully created",
                    "playlist creation summary"
                ])
                
                # Check specifically for cancellation messages
                cancellation_detected = any(phrase in output_text for phrase in [
                    "no file selected",
                    "operation cancelled"
                ])
                
                # Also check if the output is very short (suggesting the file dialog was just opened and closed)
                if len(output_text.split()) < 10 and "executing:" in output_text:
                    cancellation_detected = True
                    
            # Check if the progress is very low (suggesting we barely started)
            if self.spotify_progress1.value() < 5 and not self.phase2_active:
                cancellation_detected = True
                    
            # ONLY mark as complete if we detect explicit completion indicators and not cancellation
            if completion_detected and not cancellation_detected:
                # Complete all phases without resetting previous phases
                if self.spotify_progress1.value() < 100:
                    self.spotify_progress1.setValue(100)
                    self.spotify_status1.setText("Completed successfully")
                
                # Force Phase 2 to complete
                self.spotify_progress2.setValue(100)
                self.spotify_status2.setText("Completed successfully")
                
                self.log_spotify_output("Spotify Client completed successfully.")
                self.log_spotify_output("Check your Spotify Web UI for playlists.")
            else:
                # Reset Phase 2 and status, but preserve Phase 1 if we got that far
                if self.phase2_active:
                    self.spotify_progress2.setValue(0)
                    self.spotify_status2.setText("Ready")
                else:
                    # If we didn't even get to Phase 2, reset everything
                    self.spotify_progress1.setValue(0)
                    self.spotify_status1.setText("Ready")
                
                if cancellation_detected:
                    self.log_spotify_output("Operation cancelled.")
                else:
                    self.log_spotify_output("Process did not complete successfully.")
        else:
            # Reset all progress bars on failure
            self.spotify_progress1.setValue(0)
            self.spotify_progress2.setValue(0)
            
            self.spotify_status1.setText("Failed")
            self.spotify_status2.setText("Failed")
            
            self.log_spotify_output("Spotify Client process failed.")
        
        # Always reset the phase2_active flag when finished
        self.phase2_active = False
            
    def truncate_status(self, status: str, max_length: int = 70) -> str:
        # Remove any ANSI color codes that might be in the text
        status = re.sub(r'\033\[\d+m', '', status)
        
        # Filter out common prefixes that don't add value in the status display
        prefixes_to_remove = [
            "DEBUG: ", 
            "INFO: ", 
            "WORKER: ",
            "SPOTIFY: ",
            "DISCOVERY: "
        ]
        
        for prefix in prefixes_to_remove:
            if status.startswith(prefix):
                status = status[len(prefix):]
                break
        
        if any(phrase in line.lower() for phrase in [
            "pausing for",
            "to respect rate limit",
            "sleeping to respect",
            "respecting rate limit"
        ]):
            return False
        
        # Smart truncation - try to keep the most important part
        if len(status) <= max_length:
            return status
        else:
            # Try to find a good breaking point
            last_space = status[:max_length-3].rfind(' ')
            if last_space > max_length/2:  # Only break at space if it's reasonably positioned
                return status[:last_space] + "..."
            else:
                return status[:max_length-3] + "..."
            
    def closeEvent(self, event):
        """
        Handle application shutdown.
        
        Args:
            event: Close event
        """
        # Terminate any running processes
        if self.discovery_worker and self.discovery_worker.isRunning():
            self.discovery_worker.stop()
            
        if self.spotify_worker and self.spotify_worker.isRunning():
            self.spotify_worker.stop()
            
        event.accept()


def main():
    """Main entry point for the application."""
    # Create the application
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Find the icon path
    if getattr(sys, 'frozen', False):
        # We're running in a bundle (PyInstaller)
        base_dir = os.path.dirname(sys.executable)
    else:
        # We're running in a normal Python environment
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Look for icon in standard locations
    icon_path = os.path.join(base_dir, "genregenius.ico")
    if not os.path.exists(icon_path):
        # Try alternative locations
        alternative_paths = [
            os.path.join(base_dir, "icons", "genregenius.ico"),
            os.path.join(base_dir, "_internal", "genregenius.ico"),
        ]
        
        for path in alternative_paths:
            if os.path.exists(path):
                icon_path = path
                print(f"Found icon at: {path}")
                break
        else:
            print("Warning: No icon file found")
            icon_path = None
    else:
        print(f"Using icon from: {icon_path}")
    
    # Set application icon if icon was found
    if icon_path:
        try:
            app_icon = QIcon(icon_path)
            app.setWindowIcon(app_icon)
        except Exception as e:
            print(f"Error setting application icon: {e}")
    
    # Create the main window
    window = SpotifyLauncher()
    window.show()
    
    # Start the event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
    
