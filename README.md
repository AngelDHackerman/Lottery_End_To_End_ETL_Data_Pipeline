# End-to-End Data Pipeline for Santa Lucía Lottery: Historical Data Mining, Web Scraping, ETL, and Dynamic Visualization

## 📷 Architectural Diagrams

Below you'll find two diagrams representing both possible states of the VPC architecture:

### 1. NAT Gateway OFF
Used for cost-efficient operation during exploratory data analysis (EDA) inside Amazon SageMaker Studio Lab.  
Internet access is disabled; only the **VPC Gateway Endpoint to S3 (vpce-s3-prod)** is active for private subnet communication with S3 buckets.

![NAT OFF Architecture](./images/Santa_Lucia_Lottery+(NAT-OFF).png)

---

### 2. NAT Gateway ON
Enables internet access (via NAT Gateway + Elastic IP) from private subnets when downloading dependencies, libraries, or updates.  
The public subnet is associated with a route table that points to the Internet Gateway, while private subnets route through the NAT.

![NAT ON Architecture](./images/Santa_Lucia_Lottery_(NAT-ON).png)

---

### 3. ETL Full Serverless Diagram

1. The process starts with **Amazon EventBridge**, which triggers every Monday (weekly) and activates a Python-based **AWS Lambda function** for data extraction.

2. It fetches **.txt files** from the target website via a proxy and stores them into two **Amazon S3 buckets**: one with a simple structure, and another in Hive-style partitioning.

3. A **Glue Job** then transforms the `.txt` data into `.parquet` files and saves the results back into the corresponding S3 buckets.

4. Next, an **AWS Glue Crawler** updates the **Data Catalog**, making the data queryable through **Amazon Athena** and ready for visualization in **Amazon QuickSight**.

![ETL Full Serverless Diagram](./images/ETL-AWS-Workflow.png)


---

### 4. Step Functions Workflow 
This is how each Monday (Weekly) the stepFunctions machine works and orchestrate the ETL workflow in AWS

![StepFunctions Workflow](./images/stepfunctions_graph.png)

---

This dual-state design demonstrates cloud architecture flexibility based on workflow needs (data-only vs. development).

These diagramas were created in lucidchart.com



## **Description:** 

In this project I tried to answer and discover insights about **"Loteria Santa Lucia de Guatemala"** which is the biggest lottery in my country (Guatemala). Also to create a historical dataset for their winnig number, due to the fact that there is no way to retrieve the old data from the past draws.

## **Table of Contents**
1. [Description](#description)
2. [Why of this project?](#why-of-this-project)
3. [Automated ETL Process for Loteria Santa Lucia Data](#automated-etl-process-for-loteria-santa-lucia-data)
   - [ETL Architecture](#etl-architecture)
   - [Extract Phase](#extract-phase)
   - [Transform Phase](#transform-phase)
   - [Results](#results)
   - [Future Steps](#future-steps)
4. [Requisites](#requisites)
5. [Insights and Findings from Visualizations EDA 2024 - 01/2025](./eda_2024-01_2025.md)
6. [Technologies and Tools Used](#technologies-and-tools-used-🛠️)
7. [Project Structure](#project-structure)
8. [Next Steps](#next-steps)
9. [Acknowledgements](#acknowledgements)


## **Why of this project?** [Go Back ⬆️](#table-of-contents)

Lotería Santa Lucía is the largest and oldest lottery in Guatemala, founded in 1956. Unfortunately, there is no way to retrieve historical data other than through old physical newspapers, some Facebook videos (available only since 2018), or by purchasing old newspapers (PDFs) from the "National Newspaper Archive of Guatemala," which is very expensive (I tried it...).

Once a draw expires, the data is permanently erased. There is no way to perform any kind of audit on "Lotería Santa Lucía." Surprisingly, no thesis projects or university studies from Math or Statistics students have been conducted on this topic. Additionally, there is no dataset available on platforms like Kaggle.

Due to all these factors, I found a valuable way to provide data that no one else has, which could be interesting for those interested in statistics and Machine Learning.


## **Automated ETL Process for Loteria Santa Lucia Data** [Go Back ⬆️](#table-of-contents)

### Introduction

This project focuses on automating the ETL (Extract, Transform, Load) process for Santa Lucia Lottery data. The main goal is to efficiently collect, clean, and store data to enable analysis and visualization, highlighting insights such as winning patterns, frequently rewarded locations, and more.

### ETL Architecture

⚙️ ETL Architecture  (updated 2025-06)

The pipeline is now 100 % **serverless-ready** and consists of two main stages
(*extract* → *transform & load*).  
Each stage will eventually run inside its own **AWS Lambda** function, but you can still execute them locally for development.


| Stage | What happens | Key AWS resources |
|-------|--------------|-------------------|
| **Extraction** | *extract.py* scrapes the Santa Lucía site with headless Chrome → saves a `.txt` per draw → uploads it **twice**:<br>  • `raw/sorteo_<N>.txt` &nbsp;(_simple bucket_)<br>  • `raw/year=<YYYY>/sorteo=<N>/…` &nbsp;(_partitioned bucket_)<br>Skips draws that are already present. | *S3 (simple + partitioned)*<br>*Secrets Manager* (bucket names)<br>*VPC Gateway Endpoint* (S3) |
| **Transformation + Load** | *transformer.py* downloads any new `.txt`, splits **HEADER / BODY**, cleans with Pandas/pyarrow, and writes:<br>  • `premios_<N>.parquet`  & `sorteos_<N>.parquet` → **simple bucket**<br>  • Hive-style `processed/premios/` & `processed/sorteos/` partitioned by `year` and `sorteo` → **partitioned bucket** | *S3 (simple + partitioned)*<br>*Secrets Manager* |
| **Discovery + Query (serverless)** | A **Glue Crawler** runs on the partitioned bucket, registers tables `loteria.premios` & `loteria.sorteos`.<br>Analysts query with **Athena** or visualise in **QuickSight** without touching the VPC. | *AWS Glue Crawler*<br>*AWS Athena*<br>*AWS QuickSight* |

---

### 🟢 Extraction phase

| Item | Details |
|------|---------|
| **Tool** | Selenium + Python |
| **Script** | [`src/loteria/extractor/scraping.py`](src/loteria/extractor/scraping.py) |
| **Flow** | 1. Open awards page → dismiss pop-up<br>2. Choose ID (or latest) → click link<br>3. Parse header/body, infer real draw number & date<br>4. Write `results_raw_lottery_id_<ID>_<title>.txt`<br>5. Upload to both buckets (simple & partitioned) |
| **Idempotence** | Before scraping, the script checks `processed/year=<YYYY>/sorteo=<N>/sorteos.parquet`; if it exists, the draw is skipped. |

---

### 🟢 Transform + Load phase

| Item | Details |
|------|---------|
| **Tool** | Pandas, PyArrow, Boto3 |
| **Script** | [`src/loteria/transformer/transformer.py`](src/loteria/transformer/transformer.py) |
| **Flow** | 1. List raw `.txt` files in partitioned bucket<br>2. Skip draws already processed<br>3. Download → split HEADER/BODY<br>4. Create two DataFrames:<br>   • **sorteos** (metadata + prize digits)<br>   • **premios** (ticket, letters, amount, vendor, city, depto.)<br>5. Write Parquet to **simple bucket** (`premios_<N>.parquet`, `sorteos_<N>.parquet`)<br>6. Write partitioned Parquet (`processed/premios/`, `processed/sorteos/`) to **partitioned bucket** |
| **Data model** | Columns are strongly typed; extra columns (`year`, `sorteo`) are added before partition write. |

---

### 🟢 Resulting benefits

* **Dual-bucket strategy** → quick ad-hoc analysis (simple) **and** scalable lakehouse queries (partitioned).  
* **Glue Crawler + Athena** → zero-admin SQL layer, cheap (< $5/TB scanned).  
* **QuickSight dashboards** → shareable insights without moving data out of AWS.  
* **Ready for Lambda/Step Functions** → push-button or cron-based automation.

---

> **Note:** The old `loader.py` (MySQL/RDS) has been retired to keep the stack fully serverless and cost-efficient. Historic diagrams and EDA from 2024–2025 have been moved to [`/docs/eda_2024-01_2025.md`](docs/eda_2024-2025.md).


### Conclusion

This automated ETL project demonstrates expertise in data extraction, transformation, and storage while showcasing potential for advanced analytics and visualization. It is a robust solution for managing lottery data efficiently.


## **Technologies and Tools Used 🛠️** [Go Back ⬆️](#table-of-contents)

### 🐍 Languages and Python Libraries
- **Python 3.12** – Core language for the entire ETL pipeline.
  - **Selenium** – For headless web scraping and automation.
  - **Pandas** – For data cleaning, formatting, and transformation.
  - **PyArrow** – For writing Parquet files efficiently to S3.
  - **Boto3** – AWS SDK for Python; used for interacting with S3, Secrets Manager, and more.
  - **re / json / os** – Standard libraries used in extraction and transformation.

### ☁️ AWS Cloud Services
- **Amazon S3** – Dual-storage strategy:  
  - Simple bucket (flat files for EDA)  
  - Partitioned bucket (Hive-style for Athena/QuickSight)
- **AWS Secrets Manager** – Secure retrieval of S3 bucket names and credentials.
- **AWS Glue Crawler** – Automatically detects and registers schema + partitions for Athena.
- **Amazon Athena** – Serverless SQL engine to query Parquet data stored in S3.
- **Amazon QuickSight** – For cloud-based dashboards and storytelling.
- **(Planned)** **AWS Lambda** – Will run each ETL step serverlessly.
- **(Planned)** **AWS Step Functions / EventBridge** – For orchestration of the full pipeline.

### 💻 Development & Runtime Environment
- **Jupyter Notebooks (SageMaker Studio)** – For exploratory data analysis and chart prototyping.
- **Terraform** – Infrastructure-as-code used to provision S3, IAM, SageMaker, Glue, etc. All infra lives under [`terraform/`](./terraform/) (modular layout: `storage`, `network`, `iam`, `etl-lambda`, `etl-glue`, `catalog`, `orchestration`, `lake-formation`, `observability`, and the opt-in `sagemaker`).
- **ChromeDriver + Headless Chrome** – For scraping the official lottery website.

### 📊 Visualization & Analytics
- **Matplotlib / Seaborn** – Used for generating visual insights during EDA.
- **AWS QuickSight** – (Active phase) for producing clean, dynamic dashboards.
- **(Optional)** Dash / Streamlit – Considered for future real-time visualizations.

### ⚙️ Methods & Design Patterns
- **Serverless-first architecture** – All core services designed to run without persistent compute.
- **Dual Storage Strategy** – Separate S3 buckets for flat (notebook) and partitioned (analytics) use cases.
- **Partitioned Data Lake** – Optimized S3 structure with `year=/sorteo=` folders.
- **Modular Python code** – Scripts are atomic and Lambda-compatible.
- **Secure-by-default** – All sensitive config (bucket names, keys) are managed with Secrets Manager.


## 🔗 Reference Documentation

Below are official AWS documentation links for key services and methods used in this project:

- **Glue Crawlers and Partitioned Data Lakes**
  - [Incremental Crawls for Partitioned Data in Glue](https://docs.aws.amazon.com/glue/latest/dg/incremental-crawls.html)
  - [Adding a Glue Crawler](https://docs.aws.amazon.com/glue/latest/dg/add-crawler.html)
- **S3 Partitioning Strategy**
  - [Hive-style Partitioning in AWS Glue](https://docs.aws.amazon.com/glue/latest/dg/partitioned-data.html)
- **Athena and Querying Parquet**
  - [Using Athena with Partitioned Tables](https://docs.aws.amazon.com/athena/latest/ug/partitioning.html)
- **IAM and Secrets Management**
  - [Managing Secrets with AWS Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html)
- **Infrastructure-as-Code**
  - [Terraform AWS Provider Docs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)


## 🧠 Architectural Decisions

- [ADR-001: Separation of VPC and Serverless Services](./vpc-separation.md)



## 🚧 Challenges Faced and How They Were Overcome

Take a look to the challanged I faced and how I overcome them by giving a look to this file:

- [Challanges Faced and How They Were Overcome](./challanges_faced.md)