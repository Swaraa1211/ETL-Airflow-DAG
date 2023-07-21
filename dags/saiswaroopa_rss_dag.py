import csv
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime
import sqlite3
from airflow import DAG
from airflow.operators.dummy_operator import DummyOperator
from airflow.operators.python_operator import PythonOperator

default_args = {
    'start_date': datetime(2023, 7, 19, 23, 0), 
    'catchup': False 
}

def download_rss_feed():
    rss_url = 'https://timesofindia.indiatimes.com/rssfeedstopstories.cms'
    response = requests.get(rss_url)
    if response.status_code == 200:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"raw_rss_feed_{timestamp}.xml"
        with open(filename, 'wb') as file:
            file.write(response.content)
        return filename
    else:
        raise ValueError(f"Failed to download RSS feed. Status code: {response.status_code}")

def parse_rss_feed(**kwargs):
    ti = kwargs['ti']
    filename = ti.xcom_pull(key=None, task_ids='download_rss_feed')
    curated_filename = f"curated_{filename.replace('.xml', '.csv')}"

    tree = ET.parse(filename)
    root = tree.getroot()

    parsed_data = []
    for item in root.findall('.//item'):
        title = item.find('title').text
        link = item.find('link').text
        published = item.find('pubDate').text
        parsed_data.append({'title': title, 'link': link, 'published': published})

    with open(curated_filename, 'w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=['title', 'link', 'published'])
        writer.writeheader()
        writer.writerows(parsed_data)

    ti.xcom_push(key='curated_filename', value=curated_filename)

def load_to_db(**kwargs):
    curated_file_name = kwargs['ti'].xcom_pull(key='curated_filename')
    with open(curated_file_name, 'r', newline='') as f:
        reader = csv.reader(f)
        next(reader)  
        
        conn = sqlite3.connect('news_feeds.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS news_feeds (title text, link text, published text)''')
        
        for row in reader:
            c.execute('''INSERT INTO news_feeds (title, link, published) VALUES (?, ?, ?)''', (row[0], row[1], row[2]))
        
        conn.commit()
        conn.close()

with DAG(
    default_args=default_args,
    dag_id='RSS_feed_dag',
    start_date=datetime(2023, 7, 19, 23, 0),
    schedule_interval='0 23 * * *',
    schedule=None,
) as dag:
    start_task = DummyOperator(task_id='start_task')

    download_task = PythonOperator(
        task_id='download_rss_feed',
        python_callable=download_rss_feed
    )

    parse_task = PythonOperator(
        task_id='parse_rss_feed',
        python_callable=parse_rss_feed
    )

    load_task = PythonOperator(
        task_id='load_to_db',
        python_callable=load_to_db
    )

    end_task = DummyOperator(task_id='end_task')

    start_task >> download_task >> parse_task >> load_task >> end_task
