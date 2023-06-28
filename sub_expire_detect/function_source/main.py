"""
Copyright 2023 Google. This software is provided as-is, without warranty or 
representation for any use or purpose. Your use of it is subject to your 
agreement with Google.  
"""


from google.cloud import pubsub
from google.cloud import storage
from google.api_core import exceptions
from google.api_core import retry
import json
import os
import google.cloud.logging
import logging
import sys
import functions_framework

# set up Google Cloud Logging
cloud_logging = google.cloud.logging.Client()

def exception_logger(type, value, tb):
    logging.exception("Uncaught exception: {0}".format(str(value)))

# Install exception handler
sys.excepthook = exception_logger


# file name to store subscriber listing
blob_name="subscription_list.json"

@retry.Retry()
def get_topic_subscription_pager(client, topic_name):
    """ Retrieves subscriptions for specified topics.  Includes retry logic 
    for transient errors (e.g. 429, 500, 503)

    Args:
        client: instance of pubsub.PublisherClient()
        topic_name:  name of topic for which to retrieve subscriptions

    Returns:
        Subscription Pager
    """
    return client.list_topic_subscriptions(topic=topic_name) 


@retry.Retry()
def get_topics_pager(client, project_id):
    """ Retrieves topic pager specified project.  Includes retry logic 
    for transient errors (e.g. 429, 500, 503)

    Args:
        client: instance of pubsub.PublisherClient()
        project_id:  project id

    Returns:
        Topic Pager
    """  
    project_path  = f"projects/{project_id}"
    return client.list_topics(project=project_path)


def get_all_subscriptions(project_id):
    """ Retrieves all subscriptions from all topics for the specified project

    Args:
      project_id:  the project from which to retrieve the subscribers

    Returns:
      A dict whose keys are topic names and values are a list of subscription names.
      Topics without subscribers are not listed.  If there are no topics or no topics 
      with subscribers, an empty dict is returned.
    """

    subscriptions = {}
    client = pubsub.PublisherClient()

    topic_pager = get_topics_pager(client, project_id)
    for topic in topic_pager:
        logging.debug(f"topic={topic}")
        subscription_pager = get_topic_subscription_pager(client, topic.name)
        topic_subscriptions = []
        for subscription in subscription_pager:
            logging.debug(f"subscription={subscription}")
            topic_subscriptions.append(subscription)
        if len(topic_subscriptions) > 0:
            subscriptions[topic.name] = topic_subscriptions 

    return subscriptions



def get_previous_subscriptions_list(bucket_name):
    """ Retrieves a list of subscriptions from GCS 
    (previously stored by calling store_subscriptions_list)

    Args:
        bucket_name:  the bucket from which to retrieve the list

    Returns:
      A dict whose keys are topic names and values are a list of subscription names.
    """  
    subscriptions = {}

    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    with blob.open("r") as f:
        try:
            contents = f.read()
            subscriptions = json.loads(contents)
        except exceptions.NotFound:
            pass

    return subscriptions


def store_subscriptions_list(bucket_name, subscriptions):
    """ Stores a dict of topic subscriptions in GCS

    Args:
        bucket_name:  the bucket where to store the list
        subscriptions:  A dict whose keys are topic names and values are a list of subscription names.
    """
    contents = json.dumps(subscriptions)
    client = storage.Client(bucket_name)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    with blob.open("w") as f:
        f.write(contents)
  

def find_A_not_in_B(a, b):
    """Given dicts of lists, returns the list items in A not present in B
    
    Args:
        a: a dict of lists
        b: a dict of lists

    Returns:
        A list of items present a's lists not present in b's lists
    """
    A_not_in_B = []
    for key in a:
        X = a.get(key)
        if key in b:
            Y = b.get(key)
            A_not_in_B.append(list(set(X) - set(Y)))
        else:
            A_not_in_B.append(X)
            
    return A_not_in_B

@functions_framework.http
def main(request):

    """Compares the set of subscriptions in a project to a previous run and logs those not longer present.
    """
    level = logging.getLevelName(os.environ.get("LOG_LEVEL", logging.INFO))
    cloud_logging.setup_logging(log_level = level)
    logging.info(f"log level={level}")

    project_id = os.environ.get("PROJECT_ID", os.environ.get("GCP_PROJECT", "PROJECT_ID env var not set"))
    logging.debug(f"project_id={project_id}")

    bucket_name = os.environ.get("BUCKET","BUCKET env var not set")
    logging.debug(f"bucket_name={bucket_name}")

    current = get_all_subscriptions(project_id)
    logging.debug(f"current={current}")

    previous = get_previous_subscriptions_list(bucket_name)
    logging.debug(f"previous={previous}")

    expired = []
    if current != previous:
        expired = find_A_not_in_B(previous, current)

    store_subscriptions_list(bucket_name, current)

    logging.info(json.dumps(expired), extra={"labels":{"payload_desc":"expired subscriptions"}})

    return "success!"


if __name__ == "__main__":
    main(None)
