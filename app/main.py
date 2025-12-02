from flask import Flask, send_from_directory, jsonify, request, Response
import subprocess
import os
import zipfile
import uuid
import shutil
import threading
import time
import re

app = Flask(__name__, static_folder="web")
BASE_DOWNLOAD_FOLDER = '/app/downloads'
AUDIO_DOWNLOAD_PATH = os.getenv('AUDIO_DOWNLOAD_PATH', BASE_DOWNLOAD_FOLDER)
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
ADMIN_DOWNLOAD_PATH = AUDIO_DOWNLOAD_PATH

ignore_keywords = [
    "Extracting URL",
    "Downloading song info",
    "Downloading song URL info",
    "Downloading lyrics data",
    "[ExtractAudio]",
    "[info]",
    "[netease:song]",
    "[netease:playlist]",
]

sessions = {}

os.makedirs(BASE_DOWNLOAD_FOLDER, exist_ok=True)

@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(app.static_folder, path)

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session_id = str(uuid.uuid4())
        sessions[session_id] = username
        response = jsonify({"success": True})
        response.set_cookie("session", session_id)
        return response
    return jsonify({"success": False}), 401

def is_logged_in():
    session_id = request.cookies.get("session")
    return session_id in sessions

@app.route("/logout", methods=["POST"])
def logout():
    response = jsonify({"success": True})
    response.delete_cookie("session")
    return response

@app.route("/check-login")
def check_login():
    is_logged_in_status = is_logged_in()
    return jsonify({"loggedIn": is_logged_in_status})

@app.route("/download")
def download_media():
    spotify_link = request.args.get("spotify_link")
    if not spotify_link:
        return jsonify({"status": "error", "output": "No link provided"}), 400

    session_id = str(uuid.uuid4())
    temp_download_folder = os.path.join(BASE_DOWNLOAD_FOLDER, session_id)
    os.makedirs(temp_download_folder, exist_ok=True)

    is_admin = is_logged_in()
    
    # Spotify links
    if "spotify.com" in spotify_link or "spotify:" in spotify_link:
        command = [
            "spotdl",
            "download",
            spotify_link,
            "--output", temp_download_folder,
        ]
        is_spotify = True
    else:
        # Other links
        command = [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--add-metadata",
            "--no-part",
            "--ignore-errors",
            "--retries", "3",
            "--fragment-retries", "3",
            "--output",
            f"{temp_download_folder}/%(title)s.%(ext)s",
            spotify_link,
        ]
        is_spotify = False

    return Response(
        generate(is_admin, command, temp_download_folder, session_id, is_spotify),
        mimetype="text/event-stream",
    )

def generate(is_admin, command, temp_download_folder, session_id, is_spotify=False):
    album_name = None
    playlist_name_found = False
    current_item = None
    current_item_number = None
    total_items = 0
    downloaded_count = 0
    failed_count = 0
    errors = []

    try:
        print(f"Command: {' '.join(command)}")
        print(f"Temp folder: {temp_download_folder}")
        print(f"Spotify: {is_spotify}")
        
        # Track files before download
        start_files = set()
        for root, dirs, files in os.walk(temp_download_folder):
            for file in files:
                start_files.add(os.path.join(root, file))

        process = subprocess.Popen(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        for line in iter(process.stdout.readline, ''):
            clean_line = line.strip()
            if not clean_line:
                continue
            
            print(f"▶️ {clean_line}") 
            
            if "UserWarning" in clean_line or "pkg_resources is deprecated" in clean_line:
                continue
                
            # Capture playlist name
            if not playlist_name_found:
                patterns = [
                    r"\[download\] Downloading playlist: (.+)", 
                    r"Found \d+ songs in (.+?) \(", 
                    r"Downloading playlist: (.+)", 
                    r"Playlist: (.+)", 
                    r"Fetching playlist (.+)", 
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, clean_line)
                    if match:
                        album_name = match.group(1).strip()
                        playlist_name_found = True
                        yield f"data: 📝 Playlist name: {album_name}\n\n"
                        break
            
            # Track download progress
            item_match = re.search(r"Downloading item (\d+) of (\d+)", clean_line)
            if item_match:
                current_item_number = int(item_match.group(1))
                total_items = int(item_match.group(2))
                current_item = f"Item {current_item_number} of {total_items}"
                display_line = f"📦 Downloading {current_item}"
                yield f"data: {display_line}\n\n"
                continue
            
            # Spotify-specific output
            if is_spotify:
                if "Downloading" in clean_line and "to" in clean_line and not playlist_name_found:
                    display_line = f"⬇️ Downloading: {clean_line}"
                    yield f"data: {display_line}\n\n"
                    continue
                
                if "Downloaded" in clean_line and "%" in clean_line:
                    if "100%" in clean_line:
                        display_line = f"✅ Downloaded item {current_item_number if current_item_number else 'unknown'}"
                        yield f"data: {display_line}\n\n"
                        downloaded_count += 1
                    continue
                
                if "ERROR" in clean_line.upper() or "error" in clean_line:
                    if "100%" not in clean_line and "Downloading" not in clean_line:
                        display_line = f"⚠️ {clean_line}"
                        errors.append(clean_line)
                        failed_count += 1
                        yield f"data: {display_line}\n\n"
                        continue
                
                if "Finished downloading" in clean_line or "Saved" in clean_line:
                    display_line = f"✅ {clean_line}"
                    yield f"data: {display_line}\n\n"
                    continue
                    
                if "Fetching" in clean_line:
                    display_line = f"🔍 {clean_line}"
                    yield f"data: {display_line}\n\n"
                    continue
                
            # yt-dlp output
            else:
                if ("[download]" in clean_line and "%" in clean_line) or any(keyword in clean_line for keyword in ignore_keywords):
                    if "100%" in clean_line and "ETA" not in clean_line:
                        display_line = f"✅ Downloaded item {current_item_number if current_item_number else 'unknown'}"
                        yield f"data: {display_line}\n\n"
                        downloaded_count += 1
                    continue
                
                error_keywords = ["ERROR:", "error:", "ERROR", "error"]
                is_error = any(keyword in clean_line for keyword in error_keywords)
                
                if is_error and "100%" not in clean_line:
                    # Ignore harmless ffmpeg warnings
                    if "ffprobe" in clean_line or "ffmpeg" in clean_line:
                        display_line = "ℹ️ Warning: Audio processing tool not found, continuing anyway..."
                    else:
                        display_line = f"⚠️ {clean_line}"
                        errors.append(clean_line)
                        failed_count += 1
                    yield f"data: {display_line}\n\n"
                    continue
                
                if "Destination:" in clean_line:
                    filename = os.path.basename(clean_line.split(": ")[1] if ": " in clean_line else clean_line)
                    display_line = f"⬇️ Downloading: {filename}"
                    yield f"data: {display_line}\n\n"
                elif "Finished downloading playlist:" in clean_line or "Download complete" in clean_line:
                    display_line = f"🎉 {clean_line}"
                    yield f"data: {display_line}\n\n"
                    continue

        process.stdout.close()
        return_code = process.wait()
        
        if is_spotify and return_code != 0 and return_code != 1:
            yield f"data: ⚠️ spotdl exited with code {return_code}\n\n"
            print(f"spotdl exit code: {return_code}")

        # Get downloaded files
        end_files = set()
        for root, dirs, files in os.walk(temp_download_folder):
            for file in files:
                end_files.add(os.path.join(root, file))
        
        actual_downloaded_files = list(end_files - start_files)
        
        # Filter audio files
        valid_audio_files = [
            f for f in actual_downloaded_files 
            if f.lower().endswith((".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus"))
        ]

        if not valid_audio_files:
            for root, dirs, files in os.walk(temp_download_folder):
                for file in files:
                    if file.lower().endswith((".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus")):
                        valid_audio_files.append(os.path.join(root, file))

        # Summary
        summary = f"📊 Summary: Downloaded {len(valid_audio_files)} files, {failed_count} failed"
        yield f"data: {summary}\n\n"
        
        if errors:
            error_summary = f"⚠️ Encountered {len(errors)} error(s)"
            yield f"data: {error_summary}\n\n"
            for i, error in enumerate(errors[:3], 1):
                short_error = error[:100] + "..." if len(error) > 100 else error
                yield f"data:   {i}. {short_error}\n\n"

        if not valid_audio_files:
            yield "data: ❌ No audio files were downloaded. Please check the link and try again.\n\n"
            shutil.rmtree(temp_download_folder, ignore_errors=True)
            return

        # Admin mode
        if is_admin:
            if album_name and album_name.strip():
                final_folder_name = sanitize_filename(album_name)
            else:
                if is_spotify:
                    final_folder_name = f"Spotify_Playlist_{session_id[:8]}"
                else:
                    final_folder_name = f"Playlist_{session_id[:8]}"
            
            yield "data: 👨‍💼 Admin mode detected\n\n"
            yield f"data: 📁 Target folder: {final_folder_name}\n\n"
            
            target_directory = ADMIN_DOWNLOAD_PATH
            
            # Create target folder
            final_target_path = os.path.join(target_directory, final_folder_name)
            os.makedirs(final_target_path, exist_ok=True)
            
            yield f"data: 🚚 Processing {len(valid_audio_files)} files\n\n"
            
            moved_files = 0
            skipped_files = 0
            replaced_files = 0
            
            for file_path in valid_audio_files:
                try:
                    filename = os.path.basename(file_path)
                    safe_filename = sanitize_filename(filename)
                    
                    target_path = os.path.join(final_target_path, safe_filename)
                    
                    # Handle existing files
                    if os.path.exists(target_path):
                        new_file_size = os.path.getsize(file_path)
                        old_file_size = os.path.getsize(target_path)
                        
                        if new_file_size == old_file_size:
                            os.remove(file_path)
                            skipped_files += 1
                            yield f"data:   ⚠️ Skipped (same size): {filename}\n\n"
                            continue
                        elif new_file_size > old_file_size:
                            os.remove(target_path)
                            shutil.move(file_path, target_path)
                            replaced_files += 1
                            moved_files += 1
                            yield f"data:   🔄 Replaced (larger): {filename}\n\n"
                        else:
                            os.remove(file_path)
                            skipped_files += 1
                            yield f"data:   ⚠️ Skipped (smaller): {filename}\n\n"
                    else:
                        shutil.move(file_path, target_path)
                        moved_files += 1
                        yield f"data:   📄 Moved: {filename}\n\n"
                        
                except Exception as move_error:
                    error_msg = f"❌ Failed to process {os.path.basename(file_path)}: {str(move_error)}"
                    yield f"data: {error_msg}\n\n"
            
            # Cleanup
            try:
                shutil.rmtree(temp_download_folder, ignore_errors=True)
            except Exception:
                pass
            
            completion_msg = "✅ Admin download completed!\n"
            completion_msg += f"   Moved: {moved_files} files\n"
            completion_msg += f"   Replaced: {replaced_files} files (with larger versions)\n"
            completion_msg += f"   Skipped: {skipped_files} files\n"
            completion_msg += f"   Total: {moved_files + replaced_files} files in: {final_target_path}"
            yield f"data: {completion_msg}\n\n"
            return

        # Public user mode
        if len(valid_audio_files) > 1:
            zip_filename = f"{sanitize_filename(album_name) if album_name else 'playlist'}.zip"
            zip_path = os.path.join(temp_download_folder, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in valid_audio_files:
                    arcname = os.path.basename(file_path)
                    zipf.write(file_path, arcname=arcname)
            
            yield f"data: 📦 Created zip file: {zip_filename}\n\n"
            yield f"data: ✅ DOWNLOAD: {session_id}/{zip_filename}\n\n"
            
        else:
            from urllib.parse import quote
            relative_path = os.path.relpath(valid_audio_files[0], start=temp_download_folder)
            encoded_path = quote(relative_path)
            yield f"data: ✅ DOWNLOAD: {session_id}/{encoded_path}\n\n"
            
            threading.Thread(target=delayed_delete, args=(temp_download_folder,)).start()

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        error_msg = f"❌ Unexpected error in download process: {str(e)}"
        print(f"Error details: {error_details}")
        yield f"data: {error_msg}\n\n"
        
        try:
            shutil.rmtree(temp_download_folder, ignore_errors=True)
        except Exception:
            pass

def sanitize_filename(name):
    """Clean filenames for safe filesystem usage."""
    if not name:
        return "Unknown_Playlist"
    
    illegal_chars = r'[<>:"/\\|?*\x00-\x1f\x7f]'
    name = re.sub(illegal_chars, '_', name)
    
    name = name.strip('. ')
    
    if len(name) > 200:
        name = name[:200]
    
    return name

def delayed_delete(folder_path):
    time.sleep(300)
    try:
        shutil.rmtree(folder_path, ignore_errors=True)
        print(f"Cleaned temp folder: {folder_path}")
    except Exception:
        pass

def emergency_cleanup_container_downloads():
    print("Running cleanup in downloads folder")
    try:
        for folder in os.listdir(BASE_DOWNLOAD_FOLDER):
            folder_path = os.path.join(BASE_DOWNLOAD_FOLDER, folder)
            if os.path.isdir(folder_path) and folder != "downloads":
                try:
                    if os.path.exists(folder_path):
                        folder_age = time.time() - os.path.getctime(folder_path)
                        if folder_age > 7200:  # 2 hours
                            shutil.rmtree(folder_path, ignore_errors=True)
                            print(f"Cleaned old folder: {folder_path}")
                except Exception as e:
                    print(f"Could not delete {folder_path}: {e}")
    except Exception as e:
        print(f"Error during cleanup: {e}")

def schedule_emergency_cleanup(interval_seconds=7200):
    def loop():
        while True:
            time.sleep(interval_seconds)
            emergency_cleanup_container_downloads()
    threading.Thread(target=loop, daemon=True).start()

@app.route("/set-download-path", methods=["POST"])
def set_download_path():
    global ADMIN_DOWNLOAD_PATH
    if not is_logged_in():
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json()
    new_path = data.get("path")

    if not new_path:
        return jsonify({"success": False, "message": "Path cannot be empty."}), 400
    
    # Validate path
    if not os.path.isdir(new_path):
        try:
            os.makedirs(new_path, exist_ok=True)
        except Exception as e:
            return jsonify(
                {"success": False, "message": f"Cannot create path: {str(e)}"}
            ), 500

    ADMIN_DOWNLOAD_PATH = new_path
    return jsonify({"success": True, "new_path": ADMIN_DOWNLOAD_PATH})

@app.route("/downloads/<session_id>/<path:filename>")
def serve_download(session_id, filename):
    session_download_folder = os.path.join(BASE_DOWNLOAD_FOLDER, session_id)
    full_path = os.path.join(session_download_folder, filename)

    if ".." in filename or filename.startswith("/"):
        return "Invalid filename", 400

    if not os.path.isfile(full_path):
        return "File not found", 404

    return send_from_directory(session_download_folder, filename, as_attachment=True)

schedule_emergency_cleanup()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)