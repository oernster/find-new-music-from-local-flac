import os
import subprocess
import sys
import shutil

def create_manifest_file():
    """Create the application manifest file"""
    manifest_content = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity
    version="1.0.0.0"
    processorArchitecture="X86"
    name="PlaylistGenerator"
    type="win32"
  />
  <description>Playlist Generator</description>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <application>
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity
        type="win32"
        name="Microsoft.Windows.Common-Controls"
        version="6.0.0.0"
        processorArchitecture="*"
        publicKeyToken="6595b64144ccf1df"
        language="*"
      />
    </dependentAssembly>
  </dependency>
</assembly>'''
    
    manifest_path = "app.manifest"
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    return manifest_path

def clear_builds():
    """Clear previous builds and cache."""
    if os.path.exists('build'):
        shutil.rmtree('build')
    if os.path.exists('dist'):
        shutil.rmtree('dist')
    if os.path.exists('__pycache__'):
        shutil.rmtree('__pycache__')

def main():
    """Simple script to build the executable directly with PyInstaller"""
    print("Building Playlist Generator")
    
    clear_builds()  # Clearing previous builds and cache

    # Ensure necessary files exist
    if not os.path.exists("spotifylauncher.py"):
        print("Error: spotifylauncher.py not found in current directory.")
        return

    icon_path = "playlistgenerator.ico"
    if not os.path.exists(icon_path):
        print("Warning: playlistgenerator.ico not found")
        return
    
    print(f"Found ICO icon: {icon_path}")
    
    # Create manifest file
    manifest_path = create_manifest_file()
    
    # Build PyInstaller command
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--name=PlaylistGenerator",
        "--onefile",
        "--windowed",
        "--hidden-import=PyQt5.sip",
        "--hidden-import=PyQt5.QtSvg",
        f"--add-binary={icon_path};.",  # Ensure semicolon is used as the path separator for Windows
        f"--icon={icon_path}",
        "--log-level=DEBUG",
        "spotifylauncher.py"  # Ensure main script is included directly
    ]
    
    print("\nRunning command:")
    print(" ".join(cmd))
    
    # Run PyInstaller
    try:
        subprocess.check_call(cmd)
        print("\nBuild completed successfully!")
        print("Executable is in the 'dist' folder.")
    except subprocess.CalledProcessError as e:
        print(f"\nError building executable: {e}")
    except FileNotFoundError:
        print("\nError: PyInstaller not found. Make sure it's installed:")
        print("pip install pyinstaller")
    finally:
        # Clean up manifest file
        if os.path.exists(manifest_path):
            os.remove(manifest_path)

if __name__ == "__main__":
    main()
