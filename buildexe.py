import os
import subprocess
import sys
import shutil

def create_manifest_file():
    """Create a simpler application manifest file"""
    manifest_content = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity
    version="1.0.0.0"
    processorArchitecture="X86"
    name="GenreGenius"
    type="win32"
  />
  <description>GenreGenius</description>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
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
    """Clear previous builds, cache, and spec files."""
    if os.path.exists('build'):
        shutil.rmtree('build')
    if os.path.exists('dist'):
        shutil.rmtree('dist')
    if os.path.exists('__pycache__'):
        shutil.rmtree('__pycache__')
    
    # Also remove any existing spec files to prevent them from being reused
    for spec_file in ['PlaylistGenerator.spec', 'GenreGenius.spec']:
        if os.path.exists(spec_file):
            os.remove(spec_file)
            print(f"Removed existing spec file: {spec_file}")

def main():
    """Simple script to build the executable directly with PyInstaller"""
    print("Building GenreGenius")
    
    clear_builds()  # Clearing previous builds and cache

    # Ensure necessary files exist
    if not os.path.exists("spotifylauncher.py"):
        print("Error: spotifylauncher.py not found in current directory.")
        return

    icon_path = "genregenius.ico"
    if not os.path.exists(icon_path):
        print(f"Error: {icon_path} not found. This icon is required for the application.")
        return
    
    print(f"Found ICO icon: {icon_path}")
    
    # Create manifest file
    manifest_path = create_manifest_file()
    
    # Build PyInstaller command with explicit spec file creation
    # First, generate a custom spec file with the correct name
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['spotifylauncher.py'],
    pathex=[],
    binaries=[],
    datas=[("{icon_path}", ".")],
    hiddenimports=['PyQt5.sip', 'PyQt5.QtSvg'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GenreGenius',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="{icon_path}",
    manifest="{manifest_path}",
)
"""
    
    # Write the spec file
    spec_path = "GenreGenius.spec"
    with open(spec_path, 'w') as f:
        f.write(spec_content)
    
    print(f"Created custom spec file: {spec_path}")
    
    # Now build using this spec file
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--clean",  # Force a clean build
        spec_path
    ]
    
    # Remove empty options
    cmd = [option for option in cmd if option]
    
    print("\nRunning command:")
    print(" ".join(cmd))
    
    # Run PyInstaller
    try:
        subprocess.check_call(cmd)
        print("\nBuild completed successfully!")
        print("Executable is in the 'dist' folder.")
        
        # Copy icon to the dist folder for extra insurance
        print("Copying icon file to dist folder...")
        shutil.copy(icon_path, os.path.join("dist", icon_path))
        
        # Verify the correct executable name was created
        expected_exe = os.path.join("dist", "GenreGenius.exe")
        wrong_exe = os.path.join("dist", "PlaylistGenerator.exe")
        
        if os.path.exists(wrong_exe) and not os.path.exists(expected_exe):
            print(f"Warning: Executable was created with incorrect name.")
            print(f"Renaming {wrong_exe} to {expected_exe}")
            # Rename the executable if it was created with the wrong name
            os.rename(wrong_exe, expected_exe)
        
        # Additional info for Windows users
        if os.name == 'nt':
            print("\nImportant: If you've run previous versions of this app,")
            print("you may need to clear the Windows icon cache to see the new icon.")
            print("Instructions to clear icon cache:")
            print("1. Close all File Explorer windows")
            print("2. Open Task Manager and end the Explorer.exe process")
            print("3. From Task Manager, go to File > Run new task")
            print("4. Enter 'explorer.exe' and click OK to restart Explorer")
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