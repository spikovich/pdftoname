import argparse
import os
import re
import shutil
import sys

import pdfminer.high_level
import pdfminer.psparser
import pdfminer.pdfparser
import openai
import backoff
from langdetect import detect

MODEL = "gpt-4o-mini"

def detect_language(text):
    try:
        return detect(text)
    except:
        return "en"

def main():
    parser = argparse.ArgumentParser(description='Automatically rename PDF files.')
    parser.add_argument('filename', help='PDF file to extract text from')

    args = parser.parse_args()

    if not os.path.isfile(args.filename):
        print(f"{args.filename} is not a file.")
        sys.exit(1)

    # don't rename files that have already been renamed
    if args.filename.endswith("-PR.pdf"):
        sys.exit(0)

    try:
        text = pdfminer.high_level.extract_text(args.filename, page_numbers=[0,1,2])
    except (pdfminer.psparser.PSSyntaxError, pdfminer.pdfparser.PDFSyntaxError) as e:
        print(f"Error parsing {args.filename}. Is it a valid PDF file? Error:\n{e}")
        sys.exit(1)

    # detect language of the extracted text
    language = detect_language(text)

    # just filename from args.filename
    filename = os.path.basename(args.filename)

    if language == "en":
        prompt = f"""Given the above text extracted from the first page of an academic pdf, I would like to generate a pdf filename for the paper with the format:

        {{Title with spaces between words}}-{{year}}.pdf. 

        The year can also be in the following filename: {filename}. If the filename looks like 2402.07401.pdf, this is a pdf from arXiv and the year is 2024. If it were 2302.07401.pdf, the year would be 2023. Prefer the year from the filename. If the year is not present in either the filename or the text, use 0000. Use spaces to separates words in {{title}}. rather than dashes (-) ('This is a title' is a valid title, 'This-is-a-title' isn't, neither is 'This_is_a_title'.). The title should not be all CAPS or all lowercase. Do not output code to extract the filename. The new filename should only valid POSIX filename characters and end with the pdf extension. Your output should be just the new filename."""
    else:
        prompt = f"""Given the above text extracted from the first page of an academic pdf, I would like to generate a pdf filename for the paper with the format:

        {{Title with spaces between words}}-{{year}}.pdf. 

        The year can also be in the following filename: {filename}. If the filename looks like 2402.07401.pdf, this is a pdf from arXiv and the year is 2024. If it were 2302.07401.pdf, the year would be 2023. Prefer the year from the filename. If the year is not present in either the filename or the text, use 0000. Use spaces to separates words in {{title}}. rather than dashes (-) ('This is a title' is a valid title, 'This-is-a-title' isn't, neither is 'This_is_a_title'.). The title should not be all CAPS or all lowercase. Do not output code to extract the filename. The new filename should only valid POSIX filename characters and end with the pdf extension. Your output should be just the new filename. The text is in {language}, so please respond in {language}."""

    @backoff.on_exception(backoff.expo, openai.error.RateLimitError)
    def get_filename():
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                { "role": "system", "content": text[:7500] + "\n\n" + prompt }
            ],
            temperature=0.0,
            max_tokens=200,
        )
        
        new_filename = response["choices"][0]["message"]["content"].strip()
        # look for strings containing [0-9]{4}---*.pdf
        filenames = re.findall(r".*\.pdf", new_filename)
        if len(filenames) > 0:
            new_filename = filenames[-1]
        else:
            return None
        return new_filename
    
    new_filename = get_filename()
    
    # make sure filename is safe
    new_filename = new_filename.replace(os.sep, "-")
    if len(new_filename) > 247:
        new_filename = new_filename[:247]    

    # make sure ends in .pdf
    if not new_filename.endswith(".pdf"):
        new_filename += '.pdf'

    # replace suffix .pdf with -PR.pdf
    new_filename = new_filename.removesuffix(".pdf") + "-PR.pdf"
    base_path_original_file = os.path.dirname(args.filename)
    new_path = os.path.join(base_path_original_file, new_filename)

    # get old ctime, mtime
    ctime = os.path.getctime(args.filename)
    mtime = os.path.getmtime(args.filename)

    # rename using shutil
    # if new_path exists, append -1, -2, -3, ...
    i = 0
    while os.path.exists(new_path):
        if i == 0:
            base = new_path.removesuffix("-PR.pdf")
        else:
            base = new_path.removesuffix(f"-({i})-PR.pdf")
        i += 1
        new_path = f"{base}-({i})-PR.pdf"

    # move
    try:
        shutil.move(args.filename, new_path)
    except PermissionError as e:
        print(f"Error renaming {args.filename} to {new_path}. Permission denied. Error:\n{e}")
        sys.exit(1)
    
    # set ctime, mtime
    os.utime(new_path, (ctime, mtime))

if __name__ == "__main__":
    main()
