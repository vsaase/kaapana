from airflow.utils.log.logging_mixin import LoggingMixin
from airflow.utils.dates import days_ago
from datetime import timedelta
from airflow.models import DAG
from datetime import datetime


from kaapana.operators.Itk2DcmSegOperator import Itk2DcmSegOperator
from kaapana.operators.DcmWebSendOperator import DcmWebSendOperator
from kaapana.operators.LocalDagTriggerOperator import LocalDagTriggerOperator
from kaapana.operators.DcmConverterOperator import DcmConverterOperator
from kaapana.operators.LocalGetInputDataOperator import LocalGetInputDataOperator
from kaapana.operators.LocalWorkflowCleanerOperator import LocalWorkflowCleanerOperator

from shapemodel.OrganSegmentationOperator import OrganSegmentationOperator


log = LoggingMixin().log
dag_info = {
    "visible": True,
    "modality": ["CT"],
    "publication": {
        "doi": "10.1109/TMI.2016.2600502",
        "title": "3D Statistical Shape Models Incorporating Landmark-Wise Random Regression Forests for Omni-Directional Landmark Detection",
        "authors": "Tobias Norajitra; Klaus H. Maier-Hein",
        "confirmation": True
    }
}

args = {
    'owner': 'airflow',
    'start_date': days_ago(0),
    'retries': 1,
    'dag_info': dag_info,
    'retry_delay': timedelta(seconds=60)
}

dag = DAG(
    dag_id='shapemodel-organ-seg',
    default_args=args,
    schedule_interval=None)

timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')


get_input = LocalGetInputDataOperator(dag=dag)
# Convert DICOM to NRRD
dcm2nrrd = DcmConverterOperator(dag=dag, output_format='nrrd')

# Segment organs
organSeg_unityCS = OrganSegmentationOperator(
    dag=dag, input_operator=dcm2nrrd, mode="unityCS")

organSeg_liver = OrganSegmentationOperator(
    dag=dag, input_operator=organSeg_unityCS, mode="Liver")
organSeg_spleen = OrganSegmentationOperator(
    dag=dag, input_operator=organSeg_unityCS, mode="Spleen")
organSeg_kidney_right = OrganSegmentationOperator(
    dag=dag, input_operator=organSeg_unityCS, mode="RightKidney", spleen_operator=organSeg_spleen)
organSeg_kidney_left = OrganSegmentationOperator(
    dag=dag, input_operator=organSeg_unityCS, mode="LeftKidney", spleen_operator=organSeg_spleen)


# Convert NRRD segmentations to DICOM segmentation objects
nrrd2dcmSeg_liver = Itk2DcmSegOperator(dag=dag, segmentation_operator=organSeg_liver, single_label_seg_info="Liver", parallel_id='liver')
nrrd2dcmSeg_spleen = Itk2DcmSegOperator(dag=dag, segmentation_operator=organSeg_spleen, single_label_seg_info="Spleen", parallel_id='spleen')
nrrd2dcmSeg_kidney_right = Itk2DcmSegOperator(dag=dag, segmentation_operator=organSeg_kidney_right, single_label_seg_info="Right@Kidney", parallel_id='kidney-right')
nrrd2dcmSeg_kidney_left = Itk2DcmSegOperator(dag=dag, segmentation_operator=organSeg_kidney_left, single_label_seg_info="Left@Kidney", parallel_id='kidney-left')

# Send DICOM segmentation objects to pacs
dcmseg_send_liver = DcmWebSendOperator(dag=dag, input_operator=nrrd2dcmSeg_liver)
dcmseg_send_spleen = DcmWebSendOperator(dag=dag, input_operator=nrrd2dcmSeg_spleen)
dcmseg_send_kidney_right = DcmWebSendOperator(
    dag=dag, input_operator=nrrd2dcmSeg_kidney_right)
dcmseg_send_kidney_left = DcmWebSendOperator(
    dag=dag, input_operator=nrrd2dcmSeg_kidney_left)


trigger_radiomics_liver = LocalDagTriggerOperator(
    dag=dag, input_operator=nrrd2dcmSeg_liver, trigger_dag_id='radiomics-dcmseg')
trigger_radiomics_spleen = LocalDagTriggerOperator(
    dag=dag, input_operator=nrrd2dcmSeg_spleen, trigger_dag_id='radiomics-dcmseg')
trigger_radiomics_kidney_right = LocalDagTriggerOperator(
    dag=dag, input_operator=nrrd2dcmSeg_kidney_right, trigger_dag_id='radiomics-dcmseg')
trigger_radiomics_kidney_left = LocalDagTriggerOperator(
    dag=dag, input_operator=nrrd2dcmSeg_kidney_left, trigger_dag_id='radiomics-dcmseg')


trigger_extract_meta_liver = LocalDagTriggerOperator(
    dag=dag, input_operator=nrrd2dcmSeg_liver, trigger_dag_id='extract-metadata')
trigger_extract_meta_spleen = LocalDagTriggerOperator(
    dag=dag, input_operator=nrrd2dcmSeg_spleen, trigger_dag_id='extract-metadata')
trigger_extract_meta_kidney_right = LocalDagTriggerOperator(
    dag=dag, input_operator=nrrd2dcmSeg_kidney_right, trigger_dag_id='extract-metadata')
trigger_extract_meta_kidney_left = LocalDagTriggerOperator(
    dag=dag, input_operator=nrrd2dcmSeg_kidney_left, trigger_dag_id='extract-metadata')

clean = LocalWorkflowCleanerOperator(dag=dag)

get_input >> dcm2nrrd >> organSeg_unityCS

organSeg_unityCS >> organSeg_liver >> nrrd2dcmSeg_liver >> dcmseg_send_liver >> clean
organSeg_unityCS >> organSeg_spleen >> nrrd2dcmSeg_spleen >> dcmseg_send_spleen >> clean
organSeg_unityCS >> organSeg_kidney_right >> nrrd2dcmSeg_kidney_right >> dcmseg_send_kidney_right >> clean
organSeg_unityCS >> organSeg_kidney_left >> nrrd2dcmSeg_kidney_left >> dcmseg_send_kidney_left >> clean

organSeg_spleen >> organSeg_kidney_right
organSeg_spleen >> organSeg_kidney_left

nrrd2dcmSeg_liver >> trigger_radiomics_liver >> clean
nrrd2dcmSeg_spleen >> trigger_radiomics_spleen >> clean
nrrd2dcmSeg_kidney_right >> trigger_radiomics_kidney_right >> clean
nrrd2dcmSeg_kidney_left >> trigger_radiomics_kidney_left >> clean

nrrd2dcmSeg_liver >> trigger_extract_meta_liver >> clean
nrrd2dcmSeg_spleen >> trigger_extract_meta_spleen >> clean
nrrd2dcmSeg_kidney_right >> trigger_extract_meta_kidney_right >> clean
nrrd2dcmSeg_kidney_left >> trigger_extract_meta_kidney_left >> clean
