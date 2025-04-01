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
import ctypes
from ctypes import windll, byref, sizeof, c_int

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QLabel, 
    QTextEdit, QMenuBar, QMenu, QAction, QMessageBox, QProgressBar, QTabWidget, QWIDGETSIZE_MAX
)
from PyQt5.QtGui import QIcon, QFont, QColor, QPalette
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QMutex, QMutexLocker, pyqtSlot, QEvent


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
        Update the progress bar stylesheet based on progress percentage with dark theme colors.
        
        Args:
            value (int): Progress value (0-100)
        """
        progress_bg = "#282828"        # Dark background
        border_color = "#333333"       # Border color
        
        # Define color ranges with exact boundaries for dark theme
        if value < 1:
            # Empty/starting state
            color = "#3D3D3D"          # Dark gray
        elif value < 20:
            # Early progress - darker red in dark theme
            color = "#8B2E2E"
        elif value < 40:
            # Quarter progress - darker orange in dark theme
            color = "#B35900"
        elif value < 60:
            # Half progress - darker yellow in dark theme
            color = "#B39800"
        elif value < 80:
            # Three-quarters progress - darker green in dark theme
            color = "#639900"
        else:
            # Near completion - Spotify green
            color = "#1DB954"
            
        # Apply the stylesheet with the selected color for dark theme
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
        
        # Log the initialization
        print(f"Initializing {script_name} worker for: {script_path}")
        
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
        Extract progress information from log lines with direct percentage extraction.
        
        Args:
            line (str): Log line to process
            
        Returns:
            bool: True if progress was updated, False otherwise
        """
        try:
            # Phase transition detection
            if "starting playlist generation" in line.lower():
                self.update_progress.emit(100, "Artist Classification Complete")
                self.update_progress.emit(0, "Starting Playlist Generation")
                self.safe_emit_output("Phase transition detected: Starting playlist generation")
                return True
                
            # Look for progress percentage in exactly the format from the logs
            progress_match = re.search(r'Progress: (\d+\.\d+)% \((\d+)/(\d+) artists\)', line)
            if progress_match:
                percentage = float(progress_match.group(1))
                current = int(progress_match.group(2))
                total = int(progress_match.group(3))
                
                # Convert percentage to integer and emit the progress signal
                int_percentage = int(percentage)
                self.update_progress.emit(int_percentage, line)
                self.current_value = int_percentage  # Store the current value for reference
                return True
                
            # For "Organizing tracks for artist" messages, emit as-is without changing progress value
            if "organizing tracks for artist:" in line.lower():
                self.update_progress.emit(self.current_value, line)
                return True
                
            # Check for progress lines in different formats
            for pattern in self.progress_patterns:
                match = pattern.search(line)
                if match:
                    # If we found a percentage directly
                    if len(match.groups()) >= 1 and match.group(1) and match.group(1).replace('.', '', 1).isdigit():
                        try:
                            value = float(match.group(1))
                            int_value = int(min(100, max(0, value)))  # Ensure value is between 0-100
                            self.current_value = int_value
                            self.update_progress.emit(int_value, line)
                            return True
                        except ValueError:
                            pass
                    
            # For all other lines, don't update progress
            return False
        
        except Exception as e:
            # Log errors in progress tracking
            error_msg = f"Error in progress tracking: {str(e)}"
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
        
        # Title label with musical notes
        title = QLabel("♫  Playlist Generator ♫")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 16, QFont.Bold))
        upper_layout.addWidget(title)
        
        # Add spacer
        upper_layout.addSpacing(20)
        
        # Music Discovery button and progress section
        discovery_layout = QVBoxLayout()
        
        # Button
        self.discovery_button = QPushButton("Step 1: Music Discovery (Choose music directory)")
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
        self.spotify_button = QPushButton("Step 2: Create Spotify Playlists (Choose recommendations.json from music directory)")
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
        
        # Hide debug tab by default
        self.toggle_debug_tab(False)
        
        # Apply dark theme instead of the previous styling methods
        self.apply_dark_theme()
                
        # Set up tab changed tracking
        self.output_tabs.currentChanged.connect(self.tab_changed)
                
        # Set app and window title to dark
        palette = self.palette()
        dark_bg = QColor("#121212")
        palette.setColor(QPalette.Window, dark_bg)
        palette.setColor(QPalette.WindowText, QColor("#E0E0E0"))
        self.setPalette(palette)
        
        self.toggle_console_action.setChecked(False)  # Default to hidden logs
        self.toggle_console_output(False)             # Apply the hidden state
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

    def apply_rounded_style(self):
        """Apply rounded corners style and custom colors to the application's UI elements."""
        # Pale yellow for app background
        app_background_color = "#FFFFD0"  # Pale yellow
        button_background_color = "#B3D9FF"  # Light blue
        button_hover_color = "#99CCFF"  # Slightly darker blue for hover
        button_pressed_color = "#80BFFF"  # Even darker blue when pressed
        
        # Set main window background color
        self.central_widget.setStyleSheet(f"background-color: {app_background_color};")
        
        # Style for rounded buttons with light blue background
        button_style = f"""
            QPushButton {{
                border-radius: 8px;
                background-color: {button_background_color};
                border: 1px solid #8CB3D9;
                padding: 8px 16px;
                color: #333333;
                font-weight: bold;
            }}
            
            QPushButton:hover {{
                background-color: {button_hover_color};
            }}
            
            QPushButton:pressed {{
                background-color: {button_pressed_color};
            }}
            
            QPushButton:disabled {{
                background-color: #D9E6F2;
                color: #999999;
            }}
        """
        
        # Style for text areas (QTextEdit)
        textedit_style = """
            QTextEdit {
                border-radius: 8px;
                border: 1px solid #D9D0A3;
                padding: 5px;
                background-color: #ffffff;
            }
        """
        
        # Apply styles to buttons
        self.discovery_button.setStyleSheet(button_style)
        self.spotify_button.setStyleSheet(button_style)
        
        # Apply styles to text areas
        self.discovery_output.setStyleSheet(textedit_style)
        self.spotify_output.setStyleSheet(textedit_style)
        self.debug_output.setStyleSheet(textedit_style)
        
        # Style for the tab widget to match the rounded theme
        tab_style = f"""
            QTabWidget::pane {{
                border-radius: 8px;
                border: 1px solid #D9D0A3;
            }}
            
            QTabBar::tab {{
                border-radius: 4px 4px 0 0;
                padding: 5px 10px;
                margin-right: 2px;
                background-color: #E6E6B8;
            }}
            
            QTabBar::tab:selected {{
                background-color: {app_background_color};
            }}
            
            QTabBar::tab:hover:!selected {{
                background-color: #D9D9AD;
            }}
        """
        self.output_tabs.setStyleSheet(tab_style)
        
        # Style for labels
        label_style = """
            QLabel {
                color: #333333;
            }
        """
        self.spotify_phase1_label.setStyleSheet(label_style)
        self.spotify_phase2_label.setStyleSheet(label_style)
        self.discovery_status.setStyleSheet(label_style)
        self.spotify_status1.setStyleSheet(label_style)
        self.spotify_status2.setStyleSheet(label_style)

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
            if "♫  Playlist Generator ♫" in child.text():
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

    def setup_menu(self):
        """Set up the menu bar with options."""
        menubar = self.menuBar()
        
        # View menu
        view_menu = menubar.addMenu('View')
        
        # Toggle debug tab 
        self.toggle_debug_action = QAction('Show Debug Tab', self, checkable=True)
        self.toggle_debug_action.setChecked(False)
        self.toggle_debug_action.triggered.connect(self.safe_toggle_debug_tab)
        view_menu.addAction(self.toggle_debug_action)
        
        # Toggle console output
        self.toggle_console_action = QAction('Show Console Output', self, checkable=True)
        self.toggle_console_action.setChecked(True)  # On by default
        self.toggle_console_action.triggered.connect(self.safe_toggle_console_output)
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

    def safe_toggle_debug_tab(self, checked):
        """
        Safely toggle the debug tab with error handling.
        
        Args:
            checked (bool): Whether debug tab should be visible
        """
        try:
            self.toggle_debug_tab(checked)
        except Exception as e:
            # If any exception occurs, restore the previous state
            self.log_status(f"Error toggling debug tab: {str(e)}")
            QMessageBox.warning(self, "View Error", 
                              f"An error occurred while changing the view: {str(e)}")
            # Attempt to restore the action state (without triggering another toggle)
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
            self.toggle_console_output(checked)
        except Exception as e:
            # If any exception occurs, restore the previous state
            self.log_status(f"Error toggling console output: {str(e)}")
            QMessageBox.warning(self, "View Error", 
                              f"An error occurred while changing the view: {str(e)}")
            # Attempt to restore the action state (without triggering another toggle)
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
    Playlist Generator v2.5
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
        
        # Apply dark theme styling to the dialog
        dark_bg = "#121212"           # Dark background
        text_color = "#E0E0E0"        # Light text
        spotify_green = "#1DB954"     # Spotify green
        
        # Style the about dialog
        about_dialog.setStyleSheet(f"""
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
                padding: 6px 12px;
                font-weight: bold;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #1ED760;
            }}
            QPushButton:pressed {{
                background-color: #169C46;
            }}
        """)
        
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

        try:
            # Create and start the worker thread
            self.discovery_worker = ScriptWorker(script_path, "Music Discovery")

            # Connect signals - need to ensure proper Qt connection type
            self.discovery_worker.update_progress.connect(self.update_discovery_progress, Qt.QueuedConnection)
            self.discovery_worker.script_finished.connect(self.discovery_finished, Qt.QueuedConnection)
            self.discovery_worker.output_text.connect(self.log_status, Qt.QueuedConnection)
            self.discovery_worker.console_output.connect(self.log_discovery_output, Qt.QueuedConnection)

            # Add flag to save recommendations in music directory
            self.discovery_worker.extra_args = ["--save-in-music-dir"]

            # Log before starting the thread
            self.log_status("Music Discovery thread created, starting...")
            self.log_discovery_output("Starting Music Discovery process...")

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

    def update_discovery_progress(self, value: int, status: str):
        try:
            # Look for artist progress percentage ONLY
            progress_match = re.search(r'Progress: (\d+\.\d+)% \((\d+)/(\d+) artists\)', status)
            if progress_match:
                percentage = float(progress_match.group(1))
                current = int(progress_match.group(2))
                total = int(progress_match.group(3))
                
                # Direct update in the same thread for the progress bar
                self.discovery_progress.setValue(int(percentage))
                
                # Update status label with artists processed
                filtered_status = f"Processing: {current} of {total} artists"
                self.discovery_status.setText(filtered_status)
                
                # Log to discovery output
                self.log_discovery_output(filtered_status)
                
                return
            
            # Fallback for other meaningful status messages
            if status and len(status) > 3:
                # Filter out certain uninteresting messages
                skip_messages = [
                    "Executing:", 
                    "Working directory:", 
                    "\033", # ANSI escape codes
                    "Progress: |"  # Console progress bar
                ]
                
                if not any(msg in status for msg in skip_messages):
                    # Filter out control characters and non-printable characters
                    filtered_status = ''.join(c for c in status if c.isprintable() and ord(c) < 127)
                    
                    if filtered_status and len(filtered_status) > 3:
                        truncated_status = self.truncate_status(filtered_status)
                        self.discovery_status.setText(truncated_status)
                        self.log_discovery_output(truncated_status)
        
        except Exception as e:
            # Log the error but don't crash
            print(f"Error in update_discovery_progress: {str(e)}")

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
        try:
            # Phase transition detection
            if "starting playlist generation" in status.lower():
                # Complete Phase 1
                self.spotify_progress1.setValue(100)
                self.spotify_status1.setText("Artist Classification Complete")
                # Initialize Phase 2
                self.phase2_active = True
                self.spotify_progress2.setValue(0)
                self.spotify_status2.setText("Starting Playlist Generation")
                return
                
            # Look for specific progress updates in the format "Progress: X.X% (Y/Z artists)"
            progress_match = re.search(r'Progress: (\d+\.\d+)% \((\d+)/(\d+) artists\)', status)
            if progress_match:
                percentage = float(progress_match.group(1))
                current = int(progress_match.group(2))
                total = int(progress_match.group(3))
                
                # If we're in Phase 2 (after "Artist Classification Complete")
                if self.phase2_active:
                    # Update the Phase 2 progress bar
                    self.spotify_progress2.setValue(int(percentage))
                    self.spotify_status2.setText(f"Processing: {current} of {total} artists")
                else:
                    # Update the Phase 1 progress bar
                    self.spotify_progress1.setValue(int(percentage))
                    self.spotify_status1.setText(f"Processing artists: {current} of {total}")
                return
            
            # Handle "Organizing tracks for artist" messages in Phase 2
            if self.phase2_active and "organizing tracks for artist:" in status.lower():
                # Extract artist name
                artist_match = re.search(r'organizing tracks for artist: (.+)', status, re.IGNORECASE)
                if artist_match:
                    artist_name = artist_match.group(1)
                    self.spotify_status2.setText(f"Processing artist: {artist_name}")
                return
            
            # Regular status updates - only update text, not progress bar
            if self.phase2_active:
                self.spotify_status2.setText(self.truncate_status(status))
            else:
                # Only update status text for Phase 1 if not a progress percentage update
                self.spotify_status1.setText(self.truncate_status(status))
        except Exception as e:
            # Log the error but don't crash
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
    
