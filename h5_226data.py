# -*- coding: utf-8 -*-
"""H5_226data.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1kz9Zh2Lf3SRkEvH4s0eYeflS2wZpGe-s
"""

from airflow import DAG
from airflow.decorators import task
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook
from datetime import datetime
from airflow.models import Variable
import requests

# Default arguments for the DAG
default_args = {
    'owner': 'Divya Thakar',
    'start_date': datetime(2024, 10, 9),
    'retries': 1,
}

# Function to retrieve Snowflake connection from Airflow
def get_snowflake_conn():
    snowflake_hook = SnowflakeHook(snowflake_conn_id='my_snowflake_conn')
    return snowflake_hook.get_conn()

# Define the DAG
with DAG(
    dag_id='stock_price_snowflake_etl',
    default_args=default_args,
    schedule_interval='0 18 * * *',  # Runs daily at 6 PM
    catchup=False
) as dag:

    # Task 1: Fetch stock prices for the last 90 days from Alpha Vantage
    @task
    def last_90day_price(symbol):
        api_key = Variable.get('vantage_api_key')
        url = f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}&apikey={api_key}'
        r = requests.get(url)
        data = r.json()
        results = []

        for date, stockinfo in data['Time Series (Daily)'].items():
            stockinfo['date'] = date
            results.append(stockinfo)

        return results

    # Task 2: Create the Snowflake table
    @task
    def create_table():
        conn = get_snowflake_conn()
        create_table_query = """
        CREATE OR REPLACE TABLE raw_data.stock_price (
            open FLOAT,
            high FLOAT,
            low FLOAT,
            close FLOAT,
            volume BIGINT,
            date DATE PRIMARY KEY
        )
        """
        cur = conn.cursor()
        cur.execute(create_table_query)
        cur.close()
        conn.close()

    # Task 3: Insert data into the Snowflake table
    @task
    def insert_data(data):
        conn = get_snowflake_conn()
        cur = conn.cursor()
        try:
            insert_query = """
            INSERT INTO raw_data.stock_price (date, open, high, low, close, volume)
            VALUES (%(date)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
            """
            for record in data:
                cur.execute(insert_query, {
                    'open': record['1. open'],
                    'high': record['2. high'],
                    'low': record['3. low'],
                    'close': record['4. close'],
                    'volume': record['5. volume'],
                    'date': record['date']
                })
            cur.execute("COMMIT;")
        except Exception as e:
            cur.execute("ROLLBACK;")
            raise e
        finally:
            cur.close()
            conn.close()

    # Task 4: Ensure idempotency (no duplicate records)
    @task
    def ensure_idempotency(data):
        conn = get_snowflake_conn()
        cur = conn.cursor()

        # Count records before insertion
        cur.execute("SELECT COUNT(*) FROM raw_data.stock_price;")
        count_before = cur.fetchone()[0]

        # Insert the data
        insert_data(data)

        # Count records after insertion
        cur.execute("SELECT COUNT(*) FROM raw_data.stock_price;")
        count_after = cur.fetchone()[0]

        cur.close()
        conn.close()

        if count_before == count_after:
            print("Idempotency test passed: No duplicate records found.")
        else:
            print(f"Idempotency test failed: {count_after - count_before} new records inserted.")

    # Define task dependencies
    stock_prices = last_90day_price('AAPL')
    create_table() >> ensure_idempotency(stock_prices)