
### Separation of VPC and Serverless Services

> ⚠️ **Historical.** SageMaker Studio was removed in PR-052 (2026-10-25), so nothing described
> below as running inside the VPC exists any more. The network module is still deployed, with
> NAT off, and has no consumers.

In this project, **SageMaker Studio runs inside a private VPC** connected to S3 via a **VPC Gateway Endpoint**, which allows for local data exploration and analysis from Jupyter notebooks **without requiring internet access**.

Meanwhile, services such as **AWS Glue Crawler**, **Athena**, and **QuickSight** are configured and operate **outside the VPC**, leveraging AWS-managed network paths. This decision was made for the following reasons:

- **Simplicity in architecture**: avoids the need for VPC Interface Endpoints and additional security configuration.
- **Reduced cost**: Interface Endpoints incur hourly and per-GB charges.
- **Project context**: this is a personal project intended for demonstration purposes, not a multi-user production environment.

This separation demonstrates that a **hybrid and minimalistic architecture** can offer the best of both worlds: full technical exploration from SageMaker notebooks and effective business dashboards through QuickSight — all without incurring unnecessary operational costs.
