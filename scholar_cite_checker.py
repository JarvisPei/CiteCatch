import scholarly
import smtplib
import os
from email.message import EmailMessage
import time
import logging
from dotenv import load_dotenv

# --- Configuration ---
# Load environment variables from .env file
load_dotenv() 

# Option 1: Search by Author Name (might be ambiguous)
AUTHOR_NAME = os.getenv("AUTHOR_NAME", "Albert Einstein") 
# Option 2: Search by Google Scholar Profile ID (more reliable)
# Make sure AUTHOR_NAME is None or "" if using AUTHOR_ID
AUTHOR_ID = os.getenv("AUTHOR_ID", None) 

# Email Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com") # e.g., smtp.gmail.com for Gmail
SMTP_PORT = int(os.getenv("SMTP_PORT", 587)) # 587 for TLS, 465 for SSL
SENDER_EMAIL = os.getenv("SENDER_EMAIL") 
# For Gmail, use an App Password if 2FA is enabled
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD") 
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

# File to store the last known citation count
LAST_COUNT_FILE = "last_citation_count.txt"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Functions ---

def read_last_count(filepath):
    """Reads the last citation count from the specified file."""
    try:
        with open(filepath, 'r') as f:
            content = f.read().strip()
            if content:
                return int(content)
            else:
                logging.info(f"File {filepath} is empty, assuming initial count is 0.")
                return 0 # Assume 0 if file is empty
    except FileNotFoundError:
        logging.info(f"File {filepath} not found, assuming initial count is 0.")
        return 0 # Assume 0 if file doesn't exist
    except ValueError:
        logging.error(f"Could not parse integer from {filepath}. Assuming 0.")
        return 0 # Handle case where file content is not a number
    except Exception as e:
        logging.error(f"Error reading {filepath}: {e}. Assuming 0.")
        return 0

def write_last_count(filepath, count):
    """Writes the current citation count to the specified file."""
    try:
        with open(filepath, 'w') as f:
            f.write(str(count))
        logging.info(f"Successfully updated {filepath} with count: {count}")
    except Exception as e:
        logging.error(f"Error writing to {filepath}: {e}")

def get_citation_count(author_name=None, author_id=None):
    """Fetches the total citation count for a given author from Google Scholar."""
    if not author_name and not author_id:
        logging.error("Either author_name or author_id must be provided.")
        return None, None

    # Configure scholarly to use a free proxy provider if needed to avoid blocks
    # pg = scholarly.ProxyGenerator()
    # success = pg.FreeProxies() # Or use other proxy types like ScraperAPI, Luminati etc.
    # scholarly.scholarly.use_proxy(pg)
    
    author_info = None
    citations = None
    search_query = None

    try:
        if author_id:
            logging.info(f"Searching for author by ID: {author_id}")
            author_info = scholarly.scholarly.search_author_id(author_id)
            # Need to fill the author object to get citation count
            author_info = scholarly.scholarly.fill(author_info, sections=['basics'])
            search_query = f"ID: {author_id}" # For logging/email subject
        elif author_name:
            logging.info(f"Searching for author by name: {author_name}")
            search_query = scholarly.scholarly.search_author(author_name)
            author_info = next(search_query) # Get the first result
            # Fill the author object to get citation count
            author_info = scholarly.scholarly.fill(author_info, sections=['basics'])
            search_query = f"Name: {author_name}" # For logging/email subject

        if author_info and 'citedby' in author_info:
            citations = author_info['citedby']
            logging.info(f"Found author: {author_info.get('name', 'N/A')}, Citations: {citations}")
            return author_info.get('name', 'N/A'), citations
        else:
             logging.warning(f"Could not find citation info for the author.")
             return author_info.get('name', 'N/A') if author_info else "Unknown Author", None

    except StopIteration:
        logging.error(f"Author '{author_name}' not found.")
        return author_name, None
    except Exception as e:
        logging.error(f"An error occurred while fetching citation data: {e}")
        # Consider adding retries with delay here
        return search_query, None


def send_email(subject, body, sender, password, receiver, server, port):
    """Sends an email using SMTP."""
    if not all([sender, password, receiver, server, port]):
        logging.error("Email configuration is incomplete. Cannot send email.")
        return False
        
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = receiver
    msg.set_content(body)

    try:
        logging.info(f"Connecting to SMTP server {server}:{port}")
        with smtplib.SMTP(server, port) as smtp_server:
            smtp_server.starttls() # Enable security
            logging.info("Logging into SMTP server...")
            smtp_server.login(sender, password)
            logging.info(f"Sending email to {receiver}...")
            smtp_server.send_message(msg)
            logging.info("Email sent successfully.")
            return True
    except smtplib.SMTPAuthenticationError:
        logging.error("SMTP Authentication Error: Check sender email/password (or App Password for Gmail).")
        return False
    except Exception as e:
        logging.error(f"Failed to send email: {e}")
        return False

# --- Main Execution ---

if __name__ == "__main__":
    while True:
        try:
            logging.info("--- Starting Hourly Citation Check ---")

            # Read the last known citation count
            last_count = read_last_count(LAST_COUNT_FILE)
            logging.info(f"Last known citation count: {last_count}")

            # Determine search criteria
            target_author_name = AUTHOR_NAME
            target_author_id = AUTHOR_ID

            author_display_name = "N/A"
            total_citations = None
            search_identifier = "N/A"

            # Prefer ID if provided
            if target_author_id:
                search_identifier = f"ID: {target_author_id}"
                author_display_name, total_citations = get_citation_count(author_id=target_author_id)
            elif target_author_name:
                search_identifier = f"Name: {target_author_name}"
                author_display_name, total_citations = get_citation_count(author_name=target_author_name)
            else:
                logging.error("No author name or ID provided in environment variables. Skipping check for this cycle.")
                # No need to proceed further in this iteration if no author is specified

            # Only proceed with comparison/email if an author was specified and count retrieved
            if search_identifier != "N/A":
                if total_citations is not None:
                    # Compare with the last known count
                    if total_citations > last_count:
                        logging.info(f"New citation count ({total_citations}) is higher than the last count ({last_count}). Sending email.")

                        increase = total_citations - last_count
                        subject = f"Citation Increase for {author_display_name} (+{increase})"
                        body = f"Author Searched: {search_identifier}\n"
                        body += f"Author Found: {author_display_name}\n"
                        body += f"New Total Citations: {total_citations} (previously {last_count}, increase of {increase})\n\n"
                        body += f"Checked on: {time.strftime('%Y-%m-%d %H:%M:%S')}"

                        email_sent = send_email(subject, body, SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL, SMTP_SERVER, SMTP_PORT)

                        # Update the count file only if the email was sent successfully
                        if email_sent:
                            write_last_count(LAST_COUNT_FILE, total_citations)
                        else:
                             logging.error("Email failed to send. Last count file will not be updated.")

                    elif total_citations == last_count:
                        logging.info(f"Citation count ({total_citations}) has not changed since the last check.")
                    else:
                        # This case (count decreasing) is unlikely but possible if corrections occur on Scholar
                        logging.warning(f"Citation count ({total_citations}) is lower than the last known count ({last_count}). Not sending email, but updating count file.")
                        write_last_count(LAST_COUNT_FILE, total_citations) # Update to the lower count

                else:
                    # This case handles when get_citation_count fails for the specified author
                    logging.warning(f"Could not retrieve citation count for {search_identifier}. No comparison or email sent this cycle.")

            logging.info("--- Citation Check Cycle Finished ---")

        except Exception as e:
            # Catch any unexpected errors during the cycle to prevent the whole script crashing
            logging.error(f"An unexpected error occurred during the check cycle: {e}")
            logging.error("Script will continue to the next cycle after the delay.")

        # Wait for an hour before the next check
        logging.info("Waiting for 1 hour before next check...")
        time.sleep(3600) # 3600 seconds = 1 hour

    logging.info("--- Citation Check Finished ---") 