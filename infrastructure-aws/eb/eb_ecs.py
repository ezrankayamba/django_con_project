import pulumi
import pulumi_aws as aws
import json


config = pulumi.Config()
db_username = config.require("db_username")
db_password = config.require_secret("db_password")

# Creating a new IAM role
role = aws.iam.Role("role", assume_role_policy="""{
    "Version": "2012-10-17",
    "Statement": [{
        "Action": "sts:AssumeRole",
        "Principal": {
            "Service": "ec2.amazonaws.com"
        },
        "Effect": "Allow",
        "Sid": ""
    }]
}
""")

# Defining a policy that allows all actions on EC2 instances
policy = aws.iam.Policy("policy",
    description="A policy that allows all actions on EC2 instances",
    policy="""{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "ec2:*",
                "Effect": "Allow",
                "Resource": "*"
            }
        ]
    }"""
)

# Attaching the policy to the role
role_policy_attachment = aws.iam.RolePolicyAttachment("role_policy_attachment",
    role=role.name,
    policy_arn=policy.arn
)

# Creating an Instance Profile and adding the role to it
instance_profile = aws.iam.InstanceProfile("instance_profile", role=role.name)


default_vpc = aws.ec2.DefaultVpc(
    "default-vpc",
    tags={
        "Name": "Default VPC",
    },
)

default_az1 = aws.ec2.DefaultSubnet(
    "default-az-1",
    availability_zone="us-east-1a",
    tags={
        "Name": "Default subnet for us-east-1a",
    },
)

default_az2 = aws.ec2.DefaultSubnet(
    "default-az-2",
    availability_zone="us-east-1b",
    tags={
        "Name": "Default subnet for us-east-1b",
    },
)

default_az3 = aws.ec2.DefaultSubnet(
    "default-az-3",
    availability_zone="us-east-1d",
    tags={
        "Name": "Default subnet for us-east-1d",
    },
)


subnet_ids = pulumi.Output.all(
    default_az1.id, default_az2.id, default_az3.id
).apply(lambda az: f"{az[0]},{az[1]},{az[2]}")

vpc_to_rds = aws.ec2.SecurityGroup(
    "vpc-to-rds",
    description="Allow the resources inside the VPC to communicate with postgres RDS instance",
    vpc_id=default_vpc.id,
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            from_port=5432,
            to_port=5432,
            protocol="tcp",
            cidr_blocks=[default_vpc.cidr_block],
        )
    ],
)


def create_rds():
    rds = aws.rds.Instance(
        "rds-instance",
        allocated_storage=10,
        engine="postgres",
        engine_version="15.3",
        instance_class="db.t3.micro",
        name="testdb",
        password=db_password,
        skip_final_snapshot=True,
        username=db_username,
        vpc_security_group_ids=[vpc_to_rds.id],
    )

    conn = pulumi.Output.all(rds.address, db_password).apply(
        lambda out: f"postgresql://{db_username}:{out[1]}@{out[0]}/testdb"
    )

    return conn


def create_elastic_beanstalk_with_ecs(conn: str):
    """Creating Elastic Beanstalk"""
    # Create Elastic Beanstalk Application

    eb_application = aws.elasticbeanstalk.Application(
        "django-app", name="django-app", description="A Django test application"
    )

    # Create Elastic Beanstalk environment
    eb_environment = aws.elasticbeanstalk.Environment(
        "dev-env",
        name="dev-env",
        application=eb_application.name,
        solution_stack_name="64bit Amazon Linux 2 v3.2.13 running ECS",
        settings=[
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:elasticbeanstalk:environment",
                name="EnvironmentType",
                value="SingleInstance",
            ),
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:autoscaling:launchconfiguration",
                name="InstanceType",
                value="t2.micro",
            ),
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:autoscaling:asg",
                name="MinSize",
                value="1",
            ),
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:autoscaling:asg",
                name="MaxSize",
                value="4",
            ),
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:autoscaling:launchconfiguration",
                name="IamInstanceProfile",
                value=instance_profile.arn,
            ),
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:ec2:vpc",
                name="VPCId",
                value=default_vpc.id,
            ),
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:ec2:vpc",
                name="Subnets",
                value=subnet_ids,
            ),
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:elasticbeanstalk:environment",
                name="EnvironmentType",
                value="LoadBalanced",
            ),
            aws.elasticbeanstalk.EnvironmentSettingArgs(
                namespace="aws:elasticbeanstalk:application:environment",
                name="CONNECTION_STRING",
                value=conn,
            ),
        ],
    )

    pulumi.export("application_url", eb_environment.endpoint_url)
    pulumi.export("envId", eb_environment.id)
    pulumi.export("appName", eb_application.name)
