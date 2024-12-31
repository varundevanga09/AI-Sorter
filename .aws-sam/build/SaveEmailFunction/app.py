import json
import boto3
import email
from email import policy
import time
import openai

s3 = boto3.client('s3')
bucket_name = 'your-bucket-name-placeholder'

# OpenAI API key placeholder
openai.api_key = 'your-api-key-placeholder'

def lambda_handler(event, context):
    try:
        # Log the received SNS event for debugging
        print("Received event:", json.dumps(event, indent=4))

        for record in event['Records']:
            sns_message = record['Sns']['Message']
            print("SNS Message:", sns_message)
            
            ses_notification = json.loads(sns_message)
            source_bucket = ses_notification['receipt']['action']['bucketName']
            object_key = ses_notification['receipt']['action']['objectKey'].strip()

            if not object_key.startswith("emails/"):
                full_key = f"emails/{object_key}"
            else:
                full_key = object_key

            print(f"Bucket: {source_bucket}, Key: {full_key}")

            # Retry logic in case of delays in S3 propagation
            attempts = 3
            while attempts > 0:
                try:
                    email_object = s3.get_object(Bucket=source_bucket, Key=full_key)
                    raw_email = email_object['Body'].read().decode('utf-8')
                    print("Successfully retrieved email object from S3.")
                    break
                except s3.exceptions.NoSuchKey:
                    print("Key not found, retrying...")
                    attempts -= 1
                    time.sleep(1)

            if attempts == 0:
                raise Exception(f"Error: The key '{full_key}' could not be found after retries.")

            parsed_email = email.message_from_string(raw_email, policy=policy.default)

            # Extract metadata
            email_from = parsed_email['From']
            email_to = parsed_email['To']
            email_subject = parsed_email['Subject']
            email_date = parsed_email['Date']

            print(f"From: {email_from}")
            print(f"To: {email_to}")
            print(f"Subject: {email_subject}")
            print(f"Date: {email_date}")

            # Extract the email body (text and/or HTML)
            email_body = ""
            if parsed_email.is_multipart():
                for part in parsed_email.iter_parts():
                    content_type = part.get_content_type()
                    if content_type == 'text/plain':
                        email_body = part.get_payload(decode=True).decode('utf-8')
                        print("Plain Text Body:", email_body)
                        break  # Use the first plain text part
                    elif content_type == 'text/html' and not email_body:
                        email_body = part.get_payload(decode=True).decode('utf-8')
                        print("HTML Body found (will use if no plain text).")
            else:
                email_body = parsed_email.get_payload(decode=True).decode('utf-8')
                print("Simple Email Body:", email_body)

            if not email_body:
                raise Exception("No email body found")

            # Use the ChatCompletion API to classify the email
            response = openai.chat.completions.create(
                model="gpt-4",  # Change to "gpt-4" if available
                messages=[
                    {"role": "system", "content": "You are an assistant that classifies emails."},
                    {"role": "user", "content": f"Classify the following email: {email_body}"}
                ]
            )
            
            # Extract the classification result from the response
            classification = response.choices[0].message.content.strip()
            print("Classification result:", classification)

            # Prepare metadata and classification result
            email_metadata = {
                "From": email_from,
                "To": email_to,
                "Subject": email_subject,
                "Date": email_date,
                "Classification": classification
            }

            # Convert metadata to JSON format
            metadata_json = json.dumps(email_metadata)

            # Define the new key for storing the classification result and metadata
            classification_key = f"classifications/{object_key}.json"

            # Store the classification result and metadata in S3
            try:
                s3.put_object(
                    Bucket=source_bucket,
                    Key=classification_key,
                    Body=metadata_json,
                    ContentType='application/json'
                )
                print(f"Classification result and metadata stored at: {classification_key}")
            except Exception as e:
                print(f"Error storing classification result: {str(e)}")

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f"Error processing email: {str(e)}")
        }

    return {
        'statusCode': 200,
        'body': json.dumps('Email processed and classified successfully')
    }
