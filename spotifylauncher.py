"""
Spotify Launcher - GUI Application for Music Discovery and Spotify Playlist Creation.
"""

import sys
import os
import subprocess
import webbrowser
import time
import threading
import traceback
import queue
import re
from typing import List, Optional, Set, Tuple

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QLabel, 
    QTextEdit, QMenuBar, QMenu, QAction, QMessageBox, QProgressBar, QTabWidget
)
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal


class ColourProgressBar(QProgressBar):
    """Progress bar with color gradients that accurately reflect completion percentage."""
    
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
        Update the progress bar stylesheet based on progress percentage.
        
        Args:
            value (int): Progress value (0-100)
        """
        # Define color ranges with exact boundaries
        if value < 1:
            # Empty/starting state
            color = "#e0e0e0"  # Light gray
        elif value < 20:
            # Early progress - red
            color = "#ff5a5a"
        elif value < 40:
            # Quarter progress - orange
            color = "#ff9933"
        elif value < 60:
            # Half progress - yellow
            color = "#ffcc33" 
        elif value < 80:
            # Three-quarters progress - light green
            color = "#99cc33"
        else:
            # Near completion - green
            color = "#66cc33"
            
        # Apply the stylesheet with the selected color
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
        """
        Override setValue to update the color gradient.
        
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
        
        # Progress tracking patterns
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
            re.compile(r'Progress: \|.+?\| (\d+\.\d+)% Complete')
        ]
        
        # Additional markers for music discovery script
        self.music_discovery_patterns = [
            re.compile(r'Found (\d+) unique artists'),
            re.compile(r'Finished processing .+ in \d+\.\d+ seconds'),
            re.compile(r'Total source artists with recommendations: (\d+)'),
            re.compile(r'Music discovery complete!')
        ]

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
                self.output_text.emit(f"Found virtual environment Python at: {path}")
                return path
                
        # If no venv found, use system Python
        self.output_text.emit("No virtual environment found, using system Python")
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

    def update_progress_from_line(self, line: str) -> bool:
        """
        Extract progress information from log lines with direct percentage extraction.
        
        Args:
            line (str): Log line to process
            
        Returns:
            bool: True if progress was updated, False otherwise
        """
        try:
            # First, detect transition to Phase 2 explicitly
            if "starting playlist generation" in line.lower():
                # Emit a special signal for Phase 2 start with 0 progress
                self.output_text.emit("DETECTED PHASE TRANSITION TO PLAYLIST GENERATION")
                self.update_progress.emit(
                    0,  # Start Phase 2 at 0%
                    "phase2:" + line.strip()  # Add phase2: prefix to mark this as Phase 2
                )
                return True
                
            # Check for Phase 2 progress percentage patterns
            if "organizing tracks for artist" in line.lower():
                # This is definitely a Phase 2 message
                self.update_progress.emit(
                    self.current_value,
                    "phase2:" + line.strip()  # Add phase2: prefix
                )
                return True
            
            # Direct check for progress percentages during playlist generation
            if "progress:" in line.lower() and ("artist" in line.lower() or "track" in line.lower()):
                artists_match = re.search(r'Progress: (\d+\.\d+)% \((\d+)/(\d+)', line)
                if artists_match:
                    exact_percentage = float(artists_match.group(1))
                    current = int(artists_match.group(2))
                    total = int(artists_match.group(3))
                    
                    # Store current progress value
                    self.current_value = int(exact_percentage)
                    
                    # Check if this is likely a Phase 2 progress message
                    if "starting playlist generation" in line.lower() or "organizing tracks" in line.lower():
                        self.update_progress.emit(
                            self.current_value,
                            "phase2:Processing artists: " + str(current) + " of " + str(total)
                        )
                    else:
                        # Normal progress update for Phase 1
                        self.update_progress.emit(
                            self.current_value,
                            f"Processing artists: {current} of {total}"
                        )
                    return True
            
            # For all other messages, check if they're related to Spotify processing
            if "spotify" in self.script_name.lower():
                # File selection
                if "please select the source json file" in line.lower():
                    self.update_progress.emit(0, "Selecting JSON file...")
                    return True
                
                # JSON file initialization
                if "json file contains" in line.lower():
                    match = re.search(r'JSON file contains (\d+) total', line)
                    if match:
                        count = match.group(1)
                        self.update_progress.emit(10, f"JSON file contains {count} artists")
                        return True
                
                # Phase changes - Emit with current progress value and the status
                if "searching musicbrainz for artist" in line.lower() or "pausing for" in line.lower() or "found genre" in line.lower():
                    # Important to emit current progress value (don't reset to 0)
                    self.update_progress.emit(self.current_value, line.strip())
                    return True
            
            # Don't update progress for other lines
            return False
        
        except Exception as e:
            # Log errors in progress tracking
            error_msg = f"Error in progress tracking: {str(e)}"
            self.output_text.emit(error_msg)
            self.console_output.emit(error_msg)
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
    """Main window for the Spotify Launcher application."""
    
    def __init__(self):
        """Initialize the Spotify Launcher."""
        super().__init__()
        
        self.phase2_active = False
        
        # Configure window
        self.setWindowTitle("Playlist Generator")
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
        self.spotify_button = QPushButton("Step 2: Create Spotify Playlists (Choose created json from FLAC music directory)")
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

    def setup_menu(self):
        """Set up the menu bar with options."""
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

    def toggle_debug_tab(self, checked):
        """
        Toggle the visibility of the debug tab.
        
        Args:
            checked (bool): Whether to show the debug tab
        """
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
        Toggle the visibility of the console output tabs.
        
        Args:
            checked (bool): Whether console output should be visible
        """
        if checked:
            self.output_tabs.setVisible(True)
        else:
            self.output_tabs.setVisible(False)
        
        # Ensure no text-based progress is shown for all progress bars
        self.spotify_status1.setVisible(checked)
        self.spotify_status2.setVisible(checked)
        self.discovery_status.setVisible(checked)
        
        # Also toggle visibility of phase labels
        self.spotify_phase1_label.setVisible(checked)
        self.spotify_phase2_label.setVisible(checked)
        
        # Adjust window size to accommodate changes
        self.adjustSize()
        
    def show_about(self):
        """Show information about the application."""
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
                # Create QIcon from the icon file
                app_icon = QIcon(icon_path)
                
                # Set both the dialog icon and pixmap
                about_dialog.setWindowIcon(app_icon)
                
                # For the large icon in the dialog content, use the 64x64 size explicitly
                pixmap = app_icon.pixmap(64, 64)
                about_dialog.setIconPixmap(pixmap)
        except Exception as e:
            self.log_status(f"Error setting about dialog icon: {str(e)}")
        
        about_dialog.exec_()

    def load_set_icon(self):
        """Load and set the application icon."""
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
        Add a message to the debug output.
        
        Args:
            message (str): Message to log
        """
        if hasattr(self, 'debug_output') and self.debug_output is not None:
            self.debug_output.append(message)
            # Ensure the latest message is visible
            self.debug_output.ensureCursorVisible()
        print(message)  # Also print to console for debugging

    def log_discovery_output(self, message: str):
        """
        Add a message to the Music Discovery output.
        
        Args:
            message (str): Message to log
        """
        if hasattr(self, 'discovery_output') and self.discovery_output is not None:
            self.discovery_output.append(message)
            self.discovery_output.ensureCursorVisible()

    def log_spotify_output(self, message: str):
        """
        Add a message to the Spotify Client output.
        
        Args:
            message (str): Message to log
        """
        if hasattr(self, 'spotify_output') and self.spotify_output is not None:
            self.spotify_output.append(message)
            self.spotify_output.ensureCursorVisible()

    def launch_music_discovery(self):
        """Launch the Music Discovery script with progress tracking."""
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

    def update_discovery_progress(self, value: int, status: str):
        """
        Update discovery progress bar and status with visual feedback.
        
        Args:
            value (int): Progress value (0-100)
            status (str): Status message
        """
        # Update the progress bar
        self.discovery_progress.setValue(value)
        
        # Filter out unusual characters and problematic status messages
        if status:
            # Skip certain status messages entirely
            skip_messages = [
                "Executing:", 
                "Working directory:", 
                "\033", # ANSI escape codes
                "Progress: |"  # Console progress bar
            ]
            
            if any(msg in status for msg in skip_messages):
                return
            
            # Filter out control characters and non-printable characters
            filtered_status = ''.join(c for c in status if c.isprintable() and ord(c) < 127)
            
            # Only update if we have a meaningful filtered status
            if filtered_status and len(filtered_status) > 3:
                self.discovery_status.setText(self.truncate_status(filtered_status))
        
        # Force UI refresh
        QApplication.processEvents()

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
                
        # Create and start the worker thread
        self.spotify_worker = ScriptWorker(spotify_script, "Spotify Client")
        
        # Connect signals
        self.spotify_worker.update_progress.connect(self.update_spotify_progress)
        self.spotify_worker.script_finished.connect(self.spotify_finished)
        self.spotify_worker.output_text.connect(self.log_status)
        self.spotify_worker.console_output.connect(self.log_spotify_output)
        
        # Start the thread
        self.spotify_worker.start()
        
        # Log the start of the process
        self.log_status("Spotify Client started")
        self.log_spotify_output("Spotify Client process started...")
           
    def update_spotify_progress(self, value: int, status: str):
        """
        Update the appropriate progress bar based on the phase.
        
        Args:
            value (int): Progress value (0-100)
            status (str): Status message
        """
        # Check if this is a Phase 2 update by looking for the phase2: prefix
        if isinstance(status, str) and status.startswith("phase2:"):
            # This is a Phase 2 update, remove the prefix
            actual_status = status[7:]
            
            # If Phase 1 isn't completed yet, mark it as complete
            if self.spotify_progress1.value() < 100:
                self.spotify_progress1.setValue(100)
                self.spotify_status1.setText("Artist Classification Complete")
                
            # Set the phase2_active flag
            self.phase2_active = True
            
            # Handle "starting playlist generation" specifically
            if "starting playlist generation" in actual_status.lower():
                self.spotify_progress2.setValue(0)  # Start at 0%
                
                # Extract the total count of artists if possible
                artists_match = re.search(r'(\d+) artists across', actual_status.lower())
                if artists_match:
                    total_artists = artists_match.group(1)
                    self.spotify_status2.setText(f"Starting with {total_artists} artists")
                else:
                    self.spotify_status2.setText("Starting Playlist Generation")
            elif "progress:" in actual_status.lower():
                # Extract progress percentage
                progress_match = re.search(r'progress: (\d+\.\d+)%', actual_status.lower())
                if progress_match:
                    percentage = float(progress_match.group(1))
                    self.spotify_progress2.setValue(int(percentage))
                    
                # Update status text
                self.spotify_status2.setText(self.truncate_status(actual_status))
            else:
                # For other Phase 2 messages
                self.spotify_status2.setText(self.truncate_status(actual_status))
                
                # If organizing tracks, increment progress slightly
                if "organizing tracks for artist" in actual_status.lower():
                    current = self.spotify_progress2.value()
                    if current < 90:  # Cap at 90% until completion
                        self.spotify_progress2.setValue(min(current + 2, 90))
            return
            
        # Phase 1 updates (no phase2: prefix)
        # Handle "starting playlist generation" detection here as a fallback
        if "starting playlist generation" in status.lower():
            # This is the transition point - complete Phase 1
            self.spotify_progress1.setValue(100)
            self.spotify_status1.setText("Artist Classification Complete")
            # Reset and initialize Phase 2
            self.phase2_active = True
            self.spotify_progress2.setValue(0)
            self.spotify_status2.setText("Starting Playlist Generation")
            return
            
        # Normal Phase 1 update
        self.spotify_progress1.setValue(value)
        self.spotify_status1.setText(self.truncate_status(status))
    
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
                    "playlist url:"      # Definitive sign of completion - playlist was created
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
            if self.spotify_progress1.value() < 5:
                cancellation_detected = True
                    
            # ONLY mark as complete if we detect explicit completion indicators and not cancellation
            if completion_detected and not cancellation_detected:
                # Complete all phases without resetting previous phases
                if self.spotify_progress1.value() < 100:
                    self.spotify_progress1.setValue(100)
                    self.spotify_status1.setText("Completed successfully")
                
                if self.spotify_progress2.value() < 100:
                    self.spotify_progress2.setValue(100)
                    self.spotify_status2.setText("Completed successfully")
                
                self.log_spotify_output("Spotify Client completed successfully.")
                self.log_spotify_output("Check your Spotify Web UI for playlists.")
            else:
                # Reset Phase 2 and status, but preserve Phase 1
                self.spotify_progress2.setValue(0)
                self.spotify_status2.setText("Ready")
                
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
            
    def truncate_status(self, status: str, max_length: int = 70) -> str:
        """
        Truncate status text to reasonable length for display.
        
        Args:
            status (str): Status message to truncate
            max_length (int): Maximum length
            
        Returns:
            str: Truncated status message
        """
        if len(status) <= max_length:
            return status
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
    icon_path = os.path.join(base_dir, "playlistgenerator.ico")
    if not os.path.exists(icon_path):
        # Try alternative locations
        alternative_paths = [
            os.path.join(base_dir, "icons", "playlistgenerator.ico"),
            os.path.join(base_dir, "_internal", "playlistgenerator.ico"),
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
    
