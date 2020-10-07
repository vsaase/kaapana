from airflow.utils.log.logging_mixin import LoggingMixin
from airflow.utils.dates import days_ago
from airflow.utils.trigger_rule import TriggerRule

from datetime import timedelta

from airflow.models import DAG

from mitk_userflow.MitkInputOperator import MitkInputOperator
from kaapana.operators.LocalWorkflowCleanerOperator import LocalWorkflowCleanerOperator
from kaapana.operators.LocalGetInputDataOperator import LocalGetInputDataOperator
from kaapana.operators.DcmWebSendOperator import DcmWebSendOperator
from kaapana.operators.LocalDagTriggerOperator import LocalDagTriggerOperator
from kaapana.operators.KaapanaApplicationBaseOperator import KaapanaApplicationBaseOperator

from datetime import datetime

import os

log = LoggingMixin().log

dag_info = {
    "visible": True,
}

args = {
    'owner': 'airflow',
    'start_date': days_ago(0),
    'retries': 0,
    'dag_info': dag_info,
    'retry_delay': timedelta(seconds=30)
}

dag = DAG(
    dag_id='mitk-flow',
    default_args=args,
    schedule_interval=None)

get_input = LocalGetInputDataOperator(dag=dag)
mitk_input = MitkInputOperator(dag=dag)

launch_app = KaapanaApplicationBaseOperator(dag=dag, chart_name='mitk-flow-chart', version='0.1-vdev')
clean = LocalWorkflowCleanerOperator(dag=dag)
dcmseg_send_segmentation = DcmWebSendOperator(dag=dag, input_operator=launch_app)
trigger_extract_meta = LocalDagTriggerOperator(dag=dag, input_operator=launch_app, trigger_dag_id='extract-metadata')
clean = LocalWorkflowCleanerOperator(dag=dag)



get_input  >> mitk_input >> launch_app
launch_app >> dcmseg_send_segmentation >> clean
launch_app >> trigger_extract_meta >> clean

