import os
import uuid
import re
import traceback
import io  # <-- ADDED THIS IMPORT
from flask import (Flask, render_template, request, redirect,
                   url_for, send_file, flash)  # <-- MODIFIED THIS IMPORT (send_file instead of send_from_directory)
from bs4 import BeautifulSoup

# --- Configuration ---
# Create a Flask web server
app = Flask(__name__)
# A secret key is needed for flashing error messages
app.secret_key = "supersecretkey_change_this_later"
# Define the folder where files will be temporarily stored
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --- Core Processing Logic (Adapted from your script) ---
def process_xhtml_files(chapter_file_path, bib_file_path):
    """
    This is your original function, adapted to return the output file path on success
    or None on failure.
    """
    try:
        links_created = 0
        bib_filename = os.path.basename(bib_file_path)

        # --- Step 1: Parse Bibliography ---
        with open(bib_file_path, 'r', encoding='utf-8') as file:
            bib_soup = BeautifulSoup(file, 'xml')

        bib_data = {}
        citation_pattern = re.compile(r'^(.*?)\b(\d{4}\s*[a-z]?)\b')

        for item in bib_soup.find_all('li', id=True):
            bib_id = item['id']
            item_text = item.get_text().strip()
            match = citation_pattern.search(item_text)
            if match:
                author_part = match.group(1)
                year = match.group(2)
                if not author_part.strip():
                    continue
                try:
                    primary_author_surname = author_part.strip().split(',')[0].split()[0]
                    normalized_key = primary_author_surname.lower() + re.sub(r'\s', '', year)
                    if normalized_key not in bib_data:
                        bib_data[normalized_key] = []
                    bib_data[normalized_key].append({"id": bib_id, "filename": bib_filename})
                except IndexError:
                    continue

        if not bib_data:
            print("Warning: No valid bibliography entries found.")
            return None

        # --- Step 2: Process Chapter File ---
        with open(chapter_file_path, 'r', encoding='utf-8') as file:
            chapter_content = file.read()

        entity_map = {}
        entity_pattern = re.compile(r'(&#?\w+;)')
        def protect_entity(match):
            entity, placeholder = match.group(1), f"__ENTITY_{uuid.uuid4().hex}__"
            entity_map[placeholder] = entity
            return placeholder
        protected_content = entity_pattern.sub(protect_entity, chapter_content)

        chapter_soup = BeautifulSoup(protected_content, 'xml')
        if not chapter_soup.body:
            return None

        search_pattern = re.compile(r'\b([A-Z][a-zA-Z\']+)\s+(\d{4}\s*[a-z]?)\b')
        text_elements = chapter_soup.body.find_all(string=True)

        for text_element in text_elements:
            if text_element.parent.name in ['a', 'script', 'style']:
                continue

            original_text = str(text_element)
            matches = list(search_pattern.finditer(original_text))
            if not matches:
                continue

            new_content, last_index = [], 0
            for match in matches:
                start, end = match.span(0)
                if start > last_index:
                    new_content.append(original_text[last_index:start])

                author_in_text, year_in_text = match.group(1), match.group(2)
                lookup_key = author_in_text.lower() + re.sub(r'\s', '', year_in_text)

                if lookup_key in bib_data:
                    new_content.append(f"{author_in_text} ")
                    entry = bib_data[lookup_key][0]
                    new_a_tag = chapter_soup.new_tag("a", attrs={"class": "xref", "href": f"{entry['filename']}#{entry['id']}"})
                    new_a_tag.string = year_in_text
                    new_content.append(new_a_tag)
                    links_created += 1
                else:
                    new_content.append(match.group(0))
                last_index = end

            if last_index < len(original_text):
                new_content.append(original_text[last_index:])
            text_element.replace_with(*new_content)

        # --- Step 3: Save the Modified Chapter ---
        # Generate a unique filename for the output file
        output_filename = f"processed_{uuid.uuid4().hex}.xhtml"
        output_filepath = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)

        final_html_with_placeholders = str(chapter_soup)
        final_content = final_html_with_placeholders
        for placeholder, entity in entity_map.items():
            final_content = final_content.replace(placeholder, entity)

        with open(output_filepath, 'w', encoding='utf-8') as file:
            file.write(final_content)

        print(f"Processing complete. {links_created} links created.")
        return output_filepath

    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        traceback.print_exc()
        return None


# --- Web Routes ---
@app.route('/', methods=['GET', 'POST'])
def upload_page():
    if request.method == 'POST':
        # Check if both files were uploaded
        if 'bib_file' not in request.files or 'chapter_file' not in request.files:
            flash('Both files are required!')
            return redirect(request.url)

        bib_file = request.files['bib_file']
        chapter_file = request.files['chapter_file']

        # Check if filenames are empty
        if bib_file.filename == '' or chapter_file.filename == '':
            flash('Please select both files to upload.')
            return redirect(request.url)

        # Save uploaded files with unique names to prevent conflicts
        bib_filename = f"bib_{uuid.uuid4().hex}.xhtml"
        chapter_filename = f"chapter_{uuid.uuid4().hex}.xhtml"

        bib_path = os.path.join(app.config['UPLOAD_FOLDER'], bib_filename)
        chapter_path = os.path.join(app.config['UPLOAD_FOLDER'], chapter_filename)

        bib_file.save(bib_path)
        chapter_file.save(chapter_path)

        # Process the files
        output_path = None
        try:
            output_path = process_xhtml_files(chapter_path, bib_path)
        finally:
            # Clean up the uploaded input files
            if os.path.exists(bib_path):
                os.remove(bib_path)
            if os.path.exists(chapter_path):
                os.remove(chapter_path)

        if output_path:
            # If successful, redirect to the download link
            output_filename_only = os.path.basename(output_path)
            return redirect(url_for('download_file', filename=output_filename_only))
        else:
            # If processing failed
            flash('An error occurred during processing. Please check file formats.')
            return redirect(request.url)

    # For a GET request, just show the upload page
    return render_template('index.html')


# --- REPLACED THIS ENTIRE FUNCTION ---
@app.route('/download/<filename>')
def download_file(filename):
    # This route serves the processed file for download and then deletes it
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        # Create an in-memory stream to hold the file's data
        return_data = io.BytesIO()

        # Open the file on disk and copy its contents to the in-memory stream
        with open(filepath, 'rb') as fo:
            return_data.write(fo.read())
        
        # Rewind the in-memory stream to the beginning
        return_data.seek(0)

        # Now that the data is safely in memory, delete the file from the disk
        os.remove(filepath)

        # Send the in-memory data to the user's browser for download
        return send_file(
            return_data,
            as_attachment=True,
            download_name=filename, # Suggest the original filename to the user
            mimetype='application/xhtml+xml'
        )
    except FileNotFoundError:
        # Handle cases where the file might have already been deleted
        flash('Error: The requested file was not found. It may have already been downloaded.')
        return redirect(url_for('upload_page'))


# --- Run the Application ---
if __name__ == '__main__':
    # 'debug=True' is helpful for development
    app.run(debug=True)