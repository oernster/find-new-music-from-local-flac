import sys
import os
import subprocess
import webbrowser
import time
import threading
import traceback
import queue
import re
import random


from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QLabel, 
    QTextEdit, QMenuBar, QMenu, QAction, QMessageBox, QProgressBar, QStyleOptionProgressBar,
    QStyle, QTabWidget, QSplitter
)
from PyQt5.QtGui import QIcon, QFont, QPixmap, QColor, QPainter, QLinearGradient, QPen
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QRect, QPropertyAnimation, QEasingCurve


class ColourProgressBar(QProgressBar):
    """Progress bar with color gradients that change based on completion percentage"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(25)
        self.updateStyleSheet(0)  # Make sure it's set to zero explicitly
        self.setValue(0)          # Explicitly set initial value to 0
        
    def updateStyleSheet(self, value):
        """Update the progress bar stylesheet based on progress percentage"""
        if value == 0:
            # Neutral color when no progress
            color = "#e0e0e0"  # Ensure this is set correctly
        elif value < 20:
            # Red (start)
            color = "red"
        elif value < 40:
            # Orange
            color = "orange"
        elif value < 60:
            # Yellow
            color = "gold"
        elif value < 80:
            # Light green
            color = "yellowgreen"
        else:
            # Green (finish)
            color = "limegreen"

        self.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid grey;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                color: black;
                height: 25px;
                background-color: #f0f0f0;
            }}

            QProgressBar::chunk {{
                background-color: {color};
                width: 10px;
                margin: 0.5px;
            }}
        """)

        
    def setValue(self, value):
        """Override setValue to update the color gradient"""
        super().setValue(value)
        self.updateStyleSheet(value)


class ScriptWorker(QThread):
    """Worker thread for running Python scripts without blocking the UI"""
    update_progress = pyqtSignal(int, str, str)  # Progress value, ETA string, status message
    script_finished = pyqtSignal(bool)  # Success/failure
    output_text = pyqtSignal(str)  # Output text for debug log
    console_output = pyqtSignal(str)  # Console output for display

    def __init__(self, script_path, script_name):
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
        
        # Progress tracking patterns
        self.progress_patterns = [
            # For ProgressBar updates (match percentage complete)
            re.compile(r'Progress.*?(\d+\.\d+)%'),
            # For ETA updates
            re.compile(r'ETA: (\d+[hm])?\s?(\d+[ms])'),
            # Look for "x/y artists" patterns to extract progress
            re.compile(r'Processed: (\d+)/(\d+) artists'),
            # Spotify playlist creation progress
            re.compile(r'Creating playlist \'(.+?)\' with (\d+) tracks'),
            # MusicBrainz related progress - detect starting to process an artist
            re.compile(r'=== PROCESSING: (.+?) ==='),
            # Progress bar with percentage
            re.compile(r'Progress: \|.+?\| (\d+\.\d+)% Complete')
        ]
        
        # Additional markers for music discovery script
        self.music_discovery_patterns = [
            re.compile(r'Found (\d+) unique artists'),
            re.compile(r'Finished processing .+ in \d+\.\d+ seconds'),
            re.compile(r'Total source artists with recommendations: (\d+)'),
            re.compile(r'Music discovery complete!')
        ]

    def find_venv_python(self, script_dir):
        """Find the Python executable in a virtual environment"""
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
                self.output_text.emit(f"Found virtual environment Python at: {path}")
                return path
                
        # If no venv found, use system Python
        self.output_text.emit("No virtual environment found, using system Python")
        return "python"

    def run(self):
        """
        Run the script in a separate thread with non-blocking I/O handling.
        """
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
            self.output_text.emit(debug_cmd)
            self.console_output.emit(debug_cmd)
            
            # Output current working directory for debugging
            cwd_msg = f"Working directory: {script_dir}"
            self.output_text.emit(cwd_msg)
            self.console_output.emit(cwd_msg)
            
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
    
            # Thread for reading stdout
            def enqueue_stdout():
                try:
                    for line in iter(self.process.stdout.readline, ''):
                        stdout_queue.put(line.strip())
                    self.process.stdout.close()
                except Exception as e:
                    stdout_queue.put(f"STDOUT Error: {e}")
            
            # Thread for reading stderr
            def enqueue_stderr():
                try:
                    for line in iter(self.process.stderr.readline, ''):
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
            
            # Monitor and process output
            while self.running and self.process.poll() is None:
                # Process stdout
                try:
                    while not stdout_queue.empty():
                        line = stdout_queue.get_nowait()
                        if line:
                            self.output_text.emit(line)
                            self.console_output.emit(line)
                            self.update_progress_from_line(line)
                except queue.Empty:
                    pass
                
                # Process stderr
                try:
                    while not stderr_queue.empty():
                        line = stderr_queue.get_nowait()
                        if line:
                            error_msg = f"ERROR: {line}"
                            self.output_text.emit(error_msg)
                            self.console_output.emit(error_msg)
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
                    self.output_text.emit(line)
                    self.console_output.emit(line)
            
            while not stderr_queue.empty():
                line = stderr_queue.get()
                if line:
                    error_msg = f"ERROR: {line}"
                    self.output_text.emit(error_msg)
                    self.console_output.emit(error_msg)
            
            # Log completion status
            finish_msg = f"Process finished with return code: {return_code}"
            self.output_text.emit(finish_msg)
            self.console_output.emit(finish_msg)
            
            # Signal completion
            self.script_finished.emit(return_code == 0)
            
        except Exception as e:
            error = f"Error running script: {str(e)}\n{traceback.format_exc()}"
            self.output_text.emit(error)
            self.console_output.emit(error)
            self.running = False
            self.script_finished.emit(False)
        finally:
            self.running = False
    
    def read_stdout(self):
        """Read from process stdout in a separate thread"""
        for line in iter(self.process.stdout.readline, ''):
            if not self.running:
                break
                
            line = line.strip()
            if line:
                self.output_text.emit(line)
                self.console_output.emit(line)
                
                # Update progress based on progress patterns
                self.update_progress_from_line(line)
    
    def read_stderr(self):
        """Read from process stderr in a separate thread"""
        for line in iter(self.process.stderr.readline, ''):
            if not self.running:
                break
                
            line = line.strip()
            if line:
                error_msg = f"ERROR: {line}"
                self.output_text.emit(error_msg)
                self.console_output.emit(error_msg)

    def update_progress_from_line(self, line):
        """Extract progress information from an output line"""
        try:
            # First check for Music Discovery specific patterns
            music_discovery_patterns = [
                # For processing artists 
                re.compile(r'=== PROCESSING: (.+?) ==='),
                # For genre discovery
                re.compile(r"Found genre for '(.+?)': (.+)"),
                # For finding artists
                re.compile(r'Found (\d+) unique artists'),
                # For finding recommendations
                re.compile(r'Total source artists with recommendations: (\d+)'),
                # For MusicBrainz operations
                re.compile(r'Searching MusicBrainz for artist: (.+)')
            ]
            
            # Check each Music Discovery pattern first
            for pattern in music_discovery_patterns:
                match = pattern.search(line)
                if match:
                    if '=== PROCESSING:' in line:
                        # Processing an artist - increment progress
                        artist_name = match.group(1)
                        self.processed_artists += 1
                        
                        # Calculate percentage based on how many we've processed
                        if hasattr(self, 'total_artists') and self.total_artists > 0:
                            percentage = min(95, 5 + (self.processed_artists / self.total_artists) * 90)
                        else:
                            # If we don't know total, increment gradually
                            percentage = min(95, 5 + self.processed_artists)
                        
                        self.current_value = percentage
                        eta_string = self.calculate_eta()
                        self.update_progress.emit(int(percentage), eta_string, f"Processing: {artist_name}")
                        return
                    
                    elif 'Found genre for' in line:
                        # Found genre for an artist
                        artist_name = match.group(1)
                        genre = match.group(2)
                        # Small increment for genre finding
                        self.current_value = min(95, self.current_value + 1)
                        eta_string = self.calculate_eta()
                        self.update_progress.emit(int(self.current_value), eta_string, f"Found genre {genre} for {artist_name}")
                        return
                    
                    elif 'Found' in line and 'unique artists' in line:
                        # Found the total number of artists
                        try:
                            artist_count = int(match.group(1))
                            self.total_artists = artist_count
                            self.current_value = 5  # Start at 5%
                            self.update_progress.emit(5, "Starting...", f"Found {artist_count} artists to process")
                        except ValueError:
                            pass
                        return
                    
                    elif 'Total source artists with recommendations' in line:
                        # Near completion
                        try:
                            rec_count = int(match.group(1))
                            self.current_value = 95
                            self.update_progress.emit(95, "Almost done...", f"Generated recommendations for {rec_count} artists")
                        except ValueError:
                            pass
                        return
                    
                    elif 'Searching MusicBrainz for artist' in line:
                        artist_name = match.group(1)
                        # Small increment for each search
                        self.current_value = min(95, self.current_value + 0.5)
                        eta_string = self.calculate_eta()
                        self.update_progress.emit(int(self.current_value), eta_string, f"Searching for: {artist_name}")
                        return
                    
            # Generic progress indicators
            # Terms that indicate work is happening
            progress_terms = [
                "Processing", "Searching", "Found", "Retrieved", "Generating", 
                "Scanning", "Reading", "Writing", "Artist", "Genre", "Recommendation",
                "discovered", "filtered", "pausing"
            ]
            
            # If line contains any progress terms, update slightly
            if any(term.lower() in line.lower() for term in progress_terms):
                # Only increment a small amount
                self.current_value = min(self.current_value + 0.2, 99)
                
                # Only emit updates occasionally to avoid UI spam
                if random.random() < 0.3:
                    eta_string = self.calculate_eta()
                    self.update_progress.emit(int(self.current_value), eta_string, line[:50] + "..." if len(line) > 50 else line)
                    
        except Exception as e:
            # Log any errors in progress tracking
            error_msg = f"Error in progress tracking: {str(e)}"
            self.output_text.emit(error_msg)
            self.console_output.emit(error_msg)
            
    def calculate_eta(self):
        """Calculate estimated time to completion based on progress so far"""
        if self.current_value <= 0 or self.start_time is None:
            return "Calculating..."
            
        elapsed = time.time() - self.start_time
        if elapsed < 1:  # Less than 1 second elapsed
            return "Calculating..."
            
        progress_fraction = self.current_value / 100.0
        if progress_fraction < 0.01:  # Less than 1% progress
            return "Calculating..."
            
        total_estimated_time = elapsed / progress_fraction
        remaining_seconds = total_estimated_time - elapsed
        
        # Format the remaining time
        if remaining_seconds < 0:
            return "Almost done..."
            
        hours, remainder = divmod(int(remaining_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def stop(self):
        """Stop the running process safely"""
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                # Give it a moment to terminate gracefully
                for _ in range(10):
                    if self.process.poll() is not None:
                        self.output_text.emit("Process terminated gracefully")
                        self.console_output.emit("Process terminated gracefully")
                        break
                    time.sleep(0.1)
                
                # Force kill if still running
                if self.process.poll() is None:
                    self.process.kill()
                    self.output_text.emit("Process killed forcefully")
                    self.console_output.emit("Process killed forcefully")
            except Exception as e:
                self.output_text.emit(f"Error stopping process: {str(e)}")
                self.console_output.emit(f"Error stopping process: {str(e)}")


class SpotifyLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Configure window
        self.setWindowTitle("Playlist Generator")
        self.setMinimumSize(700, 700)  # Larger window to accommodate console output
        
        # Set up central widget with splitter
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
        
        # Title label
        title = QLabel("Playlist Generator")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 16, QFont.Bold))
        upper_layout.addWidget(title)
        
        # Add spacer
        upper_layout.addSpacing(20)
        
        # Music Discovery button and progress section
        discovery_layout = QVBoxLayout()
        
        # Button
        self.discovery_button = QPushButton("Step 1: Music Discovery (Choose FLAC music directory)")
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
        
        # Status and ETA
        discovery_status_layout = QHBoxLayout()
        self.discovery_status = QLabel("Ready")
        self.discovery_eta = QLabel("ETA: --")
        discovery_status_layout.addWidget(self.discovery_status)
        discovery_status_layout.addWidget(self.discovery_eta, alignment=Qt.AlignRight)
        discovery_layout.addLayout(discovery_status_layout)
        
        upper_layout.addLayout(discovery_layout)
        
        # Add spacer
        upper_layout.addSpacing(20)
        
        # Spotify Client button and progress section
        spotify_layout = QVBoxLayout()
        
        # Button
        self.spotify_button = QPushButton("Step 2: Create Spotify Playlists (Choose created json from FLAC music directory)")
        self.spotify_button.setFont(QFont("Arial", 12))
        self.spotify_button.setMinimumHeight(50)
        self.spotify_button.clicked.connect(self.launch_spotify_client)
        spotify_layout.addWidget(self.spotify_button)
        
        # Progress bar
        self.spotify_progress = ColourProgressBar()
        self.spotify_progress.setRange(0, 100)
        self.spotify_progress.setValue(0)
        self.spotify_progress.setFormat("")  # Clear the default format
        self.spotify_progress.setTextVisible(False)  # Hide text
        spotify_layout.addWidget(self.spotify_progress)
        
        # Status and ETA
        spotify_status_layout = QHBoxLayout()
        self.spotify_status = QLabel("Ready")
        self.spotify_eta = QLabel("ETA: --")
        spotify_status_layout.addWidget(self.spotify_status)
        spotify_status_layout.addWidget(self.spotify_eta, alignment=Qt.AlignRight)
        spotify_layout.addLayout(spotify_status_layout)
        
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
        
        # Set up the menu bar
        self.setup_menu()
        
        # Store process references
        self.discovery_worker = None
        self.spotify_worker = None
        
        # Load and set the icon
        self.load_set_icon()
            
        # Log startup information
        self.log_status("Application started")
        self.log_status(f"Running from: {self.get_base_dir()}")
        # Log Python version
        self.log_status(f"Python version: {sys.version}")
        
        # Hide debug tab by default
        self.toggle_debug_tab(False)

    def load_set_icon(self):
        """Load and set the application icon"""
        try:
            # Try to find the ICO file first
            icon_path = os.path.join(self.get_base_dir(), "playlistgenerator.ico")
            
            # If ICO not found, fall back to SVG
            if not os.path.exists(icon_path):
                icon_path = os.path.join(self.get_base_dir(), "playlistgenerator.svg")
            
            if os.path.exists(icon_path):
                self.log_status(f"Loading icon from: {icon_path}")
                app_icon = QIcon(icon_path)
                self.setWindowIcon(app_icon)
                self.log_status("Icon loaded successfully")
            else:
                self.log_status("No icon file found")
        except Exception as e:
            self.log_status(f"Error loading icon: {str(e)}")

    def setup_menu(self):
        """Set up the menu bar with options"""
        menubar = self.menuBar()
        
        # View menu
        view_menu = menubar.addMenu('View')
        
        # Toggle debug tab 
        self.toggle_debug_action = QAction('Show Debug Tab', self, checkable=True)
        self.toggle_debug_action.setChecked(False)
        self.toggle_debug_action.triggered.connect(self.toggle_debug_tab)
        view_menu.addAction(self.toggle_debug_action)
        
        # Toggle console output
        self.toggle_console_action = QAction('Show Console Output', self, checkable=True)
        self.toggle_console_action.setChecked(True)  # On by default
        self.toggle_console_action.triggered.connect(self.toggle_console_output)
        view_menu.addAction(self.toggle_console_action)
        
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
        
        # Testing menu - only in development mode
        if not getattr(sys, 'frozen', False):
            test_menu = menubar.addMenu('Testing')
            test_music_action = QAction('Run Music Discovery Directly', self)
            test_music_action.triggered.connect(self.test_run_music_discovery)
            test_menu.addAction(test_music_action)

    def test_run_music_discovery(self):
        """Directly run music discovery for testing"""
        script_path = self.find_script("musicdiscovery.py")
        if not script_path:
            self.log_status("ERROR: Could not find musicdiscovery.py!")
            return
            
        # Direct run in a subprocess
        self.log_status(f"Directly running: {script_path}")
        try:
            # Run script directly in current console
            process = subprocess.Popen(
                ["python", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Simple output handling for testing
            stdout, stderr = process.communicate()
            self.log_status(f"OUTPUT:\n{stdout}")
            if stderr:
                self.log_status(f"ERRORS:\n{stderr}")
                
            self.log_status(f"Process exited with code: {process.returncode}")
        except Exception as e:
            self.log_status(f"Error in direct run: {str(e)}")

    def toggle_debug_tab(self, checked):
        """Toggle the visibility of the debug tab"""
        # The tab is always there, we just need to handle showing/hiding it
        if checked:
            if self.output_tabs.indexOf(self.debug_output) == -1:
                self.output_tabs.addTab(self.debug_output, "Debug Log")
        else:
            idx = self.output_tabs.indexOf(self.debug_output)
            if idx >= 0:
                self.output_tabs.removeTab(idx)
                
    def toggle_console_output(self, checked):
        """
        Toggle the visibility of the console output tabs while ensuring 
        text progress indicators remain hidden.
        
        Args:
            checked (bool): Whether console output should be visible
        """
        if checked:
            self.output_tabs.setVisible(True)
        else:
            self.output_tabs.setVisible(False)
        
        # Ensure no text-based progress is shown
        self.spotify_status.setVisible(checked)
        self.spotify_eta.setVisible(checked)
        self.discovery_status.setVisible(checked)
        self.discovery_eta.setVisible(checked)
        
        # Adjust window size to accommodate changes
        self.adjustSize()
        
    def show_about(self):
        """Show information about the application using a simple message box"""
        about_text = """
Playlist Generator
By Oliver Ernster

A simple tool for discovering music and 
generating Spotify playlists.

This application provides easy access to:
• Music Discovery Tool
• Spotify Client Tool

All dependencies are bundled with this application.

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
            icon_path = os.path.join(self.get_base_dir(), "playlistgenerator.ico")
            
            # Fall back to SVG if ICO not found
            if not os.path.exists(icon_path):
                icon_path = os.path.join(self.get_base_dir(), "playlistgenerator.svg")
            
            if os.path.exists(icon_path):
                app_icon = QIcon(icon_path)
                about_dialog.setIconPixmap(app_icon.pixmap(64, 64))
        except Exception as e:
            self.log_status(f"Error setting about dialog icon: {str(e)}")
        
        about_dialog.exec_()

    def get_base_dir(self):
        """Get the directory where the executable is located"""
        if getattr(sys, 'frozen', False):
            # We're running in a bundle (PyInstaller)
            return os.path.dirname(sys.executable)
        else:
            # We're running in a normal Python environment
            return os.path.dirname(os.path.abspath(__file__)) or os.getcwd()

    def find_script(self, script_name):
        """Find a script in various possible locations"""
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

    def log_status(self, message):
        """Add a message to the debug output"""
        if hasattr(self, 'debug_output') and self.debug_output is not None:
            self.debug_output.append(message)
            # Ensure the latest message is visible
            self.debug_output.ensureCursorVisible()
        print(message)  # Also print to console for debugging

    def log_discovery_output(self, message):
        """Add a message to the Music Discovery output"""
        if hasattr(self, 'discovery_output') and self.discovery_output is not None:
            self.discovery_output.append(message)
            self.discovery_output.ensureCursorVisible()

    def log_spotify_output(self, message):
        """Add a message to the Spotify Client output"""
        if hasattr(self, 'spotify_output') and self.spotify_output is not None:
            self.spotify_output.append(message)
            self.spotify_output.ensureCursorVisible()

    def launch_music_discovery(self):
        """Launch the Music Discovery script with progress tracking"""
        if self.discovery_worker and self.discovery_worker.isRunning():
            self.log_status("Music Discovery is already running")
            return

        # Reset UI
        self.discovery_progress.setValue(0)
        self.discovery_status.setText("Starting...")
        self.discovery_eta.setText("ETA: Calculating...")
        self.discovery_button.setEnabled(False)
        
        # Disable the Spotify button while Music Discovery is running
        self.spotify_button.setEnabled(False)

        # Clear the output text
        self.discovery_output.clear()

        # Activate the Music Discovery output tab
        self.output_tabs.setCurrentWidget(self.discovery_output)

        # Find the script
        script_path = self.find_script("musicdiscovery.py")
        if not script_path:
            self.log_status("ERROR: Could not find musicdiscovery.py!")
            self.discovery_button.setEnabled(True)
            self.spotify_button.setEnabled(True)  # Re-enable Spotify button
            self.discovery_status.setText("Error: Script not found")
            return

        self.log_status(f"Found script at: {script_path}")

        # Create and start the worker thread
        self.discovery_worker = ScriptWorker(script_path, "Music Discovery")

        # Connect signals
        self.discovery_worker.update_progress.connect(self.update_discovery_progress)
        self.discovery_worker.script_finished.connect(self.discovery_finished)
        self.discovery_worker.output_text.connect(self.log_status)
        self.discovery_worker.console_output.connect(self.log_discovery_output)

        # Add flag to save recommendations in music directory
        self.discovery_worker.extra_args = ["--save-in-music-dir"]

        # Start the thread
        self.discovery_worker.start()

        self.log_status("Music Discovery initiated...")

    def update_discovery_progress(self, value, eta, status):
        """Update discovery progress bar and status"""
        # Only update if value is greater than current value
        # This prevents "jumping back" in progress
        current_value = self.discovery_progress.value()
        if value >= current_value or value == 0:  # Allow explicit reset to 0
            self.discovery_progress.setValue(value)
            
            # Update ETA with a simpler format
            if eta and eta != "Calculating...":
                self.discovery_eta.setText(f"ETA: {eta}")
            else:
                self.discovery_eta.setText("ETA: Calculating...")
            
            # Truncate status and remove progress text
            self.discovery_status.setText(self.truncate_status(status))

    def discovery_finished(self, success):
        """Handle when music discovery is finished"""
        self.discovery_button.setEnabled(True)
        
        # Re-enable the Spotify button when Music Discovery completes
        self.spotify_button.setEnabled(True)
        
        if success:
            # Check if we actually processed files (not just cancelled the dialog)
            if self.discovery_progress.value() > 10 or "complete" in self.discovery_status.text().lower():
                # Real completion - keep at 100%
                self.discovery_progress.setValue(100)
                self.discovery_status.setText("Completed successfully")
                self.discovery_eta.setText("ETA: Complete")
                self.log_discovery_output("Music Discovery completed successfully.")
            else:
                # User likely cancelled file selection - reset to 0%
                self.discovery_progress.setValue(0)
                self.discovery_status.setText("Ready")
                self.discovery_eta.setText("ETA: --")
                self.log_discovery_output("Operation cancelled.")
        else:
            # Reset on failure
            self.discovery_progress.setValue(0)
            self.discovery_status.setText("Failed")
            self.discovery_eta.setText("ETA: --")
            self.log_discovery_output("Music Discovery process failed.")

    def launch_spotify_client(self):
        """Launch the Spotify Client script with progress tracking"""
        if self.spotify_worker and self.spotify_worker.isRunning():
            # Script is already running
            self.log_status("Spotify Client is already running")
            return
                
        # Reset UI
        self.spotify_progress.setValue(0)
        self.spotify_status.setText("Starting...")
        self.spotify_eta.setText("ETA: Calculating...")
        self.spotify_button.setEnabled(False)
        
        # Disable the Music Discovery button while Spotify Client is running
        self.discovery_button.setEnabled(False)
        
        # Clear the output text
        self.spotify_output.clear()
        
        # Activate the Spotify Client output tab
        self.output_tabs.setCurrentWidget(self.spotify_output)
                
        # Find the script
        spotify_script = None
        for script_name in ["spotifyclient.py", "newspotifyclient.py"]:
            script_path = self.find_script(script_name)
            if script_path:
                spotify_script = script_path
                self.log_status(f"Found Spotify client script: {script_name}")
                break
                    
        if not spotify_script:
            self.log_status("ERROR: Could not find any Spotify client script!")
            self.spotify_button.setEnabled(True)
            self.discovery_button.setEnabled(True)  # Re-enable Music Discovery button
            self.spotify_status.setText("Error: Script not found")
            return
                
        # Create and start the worker thread
        self.spotify_worker = ScriptWorker(spotify_script, "Spotify Client")
        
        # Connect signals
        self.spotify_worker.update_progress.connect(self.update_spotify_progress)
        self.spotify_worker.script_finished.connect(self.spotify_finished)
        self.spotify_worker.output_text.connect(self.log_status)
        self.spotify_worker.console_output.connect(self.log_spotify_output)
        
        # Start the thread
        self.spotify_worker.start()
        self.log_status("Spotify Client started")
        self.log_spotify_output("Spotify Client process started...")

    def update_discovery_progress(self, value, eta, status):
        """Update discovery progress bar and status"""
        # Only update if value is greater than current value
        # This prevents "jumping back" in progress
        current_value = self.discovery_progress.value()
        if value >= current_value or value == 0:  # Allow explicit reset to 0
            self.discovery_progress.setValue(value)
            self.discovery_eta.setText(f"ETA: {eta}")
            self.discovery_status.setText(self.truncate_status(status))
            
    def update_spotify_progress(self, value, eta, status):
        """Update spotify progress bar and status"""
        # Only update if value is greater than current value
        # This prevents "jumping back" in progress
        current_value = self.spotify_progress.value()
        if value >= current_value or value == 0:  # Allow explicit reset to 0
            self.spotify_progress.setValue(value)
            
            # Update ETA with a simpler format
            if eta and eta != "Calculating...":
                self.spotify_eta.setText(f"ETA: {eta}")
            else:
                self.spotify_eta.setText("ETA: Calculating...")
            
            # Truncate status and remove progress text
            self.spotify_status.setText(self.truncate_status(status))

    def spotify_finished(self, success):
        """Handle when spotify client is finished"""
        self.spotify_button.setEnabled(True)
        
        # Re-enable the Music Discovery button when Spotify Client completes
        self.discovery_button.setEnabled(True)
        
        if success:
            # Check if progress is still at the initial value
            # If so, assume user cancelled the file/folder selection
            current_progress = self.spotify_progress.value()
            if current_progress <= 10:
                self.spotify_progress.setValue(0)  # Keep at 0%
                self.spotify_status.setText("Ready")
                self.spotify_eta.setText("ETA: --")
                self.log_spotify_output("Operation cancelled.")
                return
                    
            # Normal successful completion
            self.spotify_progress.setValue(100)
            self.spotify_status.setText("Completed successfully.")
            self.spotify_eta.setText("ETA: Complete")
            self.log_spotify_output("Spotify Client completed successfully.")
            self.log_spotify_output("Check your Spotify Web UI for playlists.")
                
        else:
            # Reset on failure
            self.spotify_progress.setValue(0)
            self.spotify_status.setText("Failed") 
            self.spotify_eta.setText("ETA: --")
            self.log_spotify_output("Spotify Client process failed.")
            
    def truncate_status(self, status, max_length=70):
        """Truncate status text to reasonable length for display"""
        if len(status) <= max_length:
            return status
        else:
            return status[:max_length-3] + "..."
            
    def closeEvent(self, event):
        """Handle application shutdown"""
        # Terminate any running processes
        if self.discovery_worker and self.discovery_worker.isRunning():
            self.discovery_worker.stop()
            
        if self.spotify_worker and self.spotify_worker.isRunning():
            self.spotify_worker.stop()
            
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    window = SpotifyLauncher()
    window.show()
    
    sys.exit(app.exec_())