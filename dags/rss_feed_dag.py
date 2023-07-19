from datetime import datetime, timedelta
import requests
import xml.etree.ElementTree as ET
import csv
import pandas as pd
from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.operators.bash_operator import BashOperator
from airflow.operators.dummy_operator import DummyOperator
from airflow.models import XCom
from airflow.models import Variable

default_args = {
    'owner': 'airflow',
    'retries': 5,
    'retry_delay': timedelta(minutes=5)
}


def extract_data(**context):
    url = 'https://timesofindia.indiatimes.com/rssfeedstopstories.cms'
    response = requests.get(url)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f'raw_rss_feed_{timestamp}.xml'

    with open(filename, 'w') as file:
        file.write(response.text)

    context['task_instance'].xcom_push(key='filename', value=filename)


def transform_data(**context):
    ti = context['task_instance']
    filename = ti.xcom_pull(key='filename')

    tree = ET.parse(filename)
    root = tree.getroot()

    items = []
    for item in root.findall('.//item'):
        title = item.find('title').text
        link = item.find('link').text
        pub_date = item.find('pubDate').text
        items.append((title, link, pub_date))

    curated_filename = f'curated_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    with open(curated_filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Title', 'Link', 'Pub Date'])
        writer.writerows(items)

    ti.xcom_push(key='curated_filename', value=curated_filename)


def load_data(**context):
    ti = context['task_instance']
    curated_filename = ti.xcom_pull(key='curated_filename')

    # Retrieve PostgreSQL credentials using Airflow's Variable
    postgres_user = 'airflow'
    postgres_password = 'airflow'
    postgres_db = 'airflow'
    postgres_host = "postgres"  # Use the container service name as the host

    # Connection string for PostgreSQL
    conn_str = f"postgresql+psycopg2://{postgres_user}:{postgres_password}@{postgres_host}/{postgres_db}"

    df = pd.read_csv(curated_filename)
    df.to_sql('NEWS_FEED', conn_str, if_exists='append', index=False)


with DAG(
    default_args=default_args,
    dag_id='RSS_feed_dag',
    start_date=datetime(2023, 7, 19, 23, 0),
    schedule_interval='0 23 * * *',
    schedule= None,
)as dag:

    download_task = PythonOperator(
        task_id='Extraction',
        python_callable=extract_data,
        provide_context=True,
    )

    parse_task = PythonOperator(
        task_id='Transformation',
        python_callable=transform_data,
        provide_context=True,
    )

    load_task = PythonOperator(
        task_id='load_to_database',
        python_callable=load_data,
        provide_context=True,
    )


    download_task >> parse_task >> load_task