import boto3
import os
import time
import base64

# === Configuration ===
REGION = "eu-central-1"
PROJECT_NAME = "vijay-new-3-backend-project"
KEY_NAME = f"{PROJECT_NAME}-key"
KEY_PATH = f"C:\\Users\\Pranvi Kankane\\OneDrive\\Desktop\\VLearn-boto-3-project\\{KEY_NAME}.pem"
AMI_ID = "ami-0df7a207adb9748c7"  # Amazon Linux 2 (replace if region differs)
INSTANCE_TYPE = "t3.medium"

# === Clients ===
ec2 = boto3.resource('ec2', region_name=REGION)
ec2_client = boto3.client('ec2', region_name=REGION)
asg_client = boto3.client('autoscaling', region_name=REGION)
elbv2_client = boto3.client('elbv2', region_name=REGION)

# === Helper Functions ===
def create_vpc():
    print("Creating VPC...")
    vpc = ec2.create_vpc(CidrBlock='10.101.0.0/16')
    vpc.wait_until_available()
    vpc.create_tags(Tags=[{'Key': 'Name', 'Value': f'{PROJECT_NAME}-vpc'}])
    print(f"Created VPC {vpc.id}")

    igw = ec2.create_internet_gateway()
    vpc.attach_internet_gateway(InternetGatewayId=igw.id)
    print(f"Attached Internet Gateway {igw.id}")

    route_table = vpc.create_route_table()
    route_table.create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=igw.id)
    print(f"Created Route Table {route_table.id}")

    return vpc, route_table

def create_public_subnets(vpc, route_table):
    print("Creating 2 public subnets...")
    subnet1 = ec2.create_subnet(
        VpcId=vpc.id, CidrBlock='10.101.1.0/24', AvailabilityZone=f'{REGION}a'
    )
    subnet2 = ec2.create_subnet(
        VpcId=vpc.id, CidrBlock='10.101.2.0/24', AvailabilityZone=f'{REGION}b'
    )

    for subnet in [subnet1, subnet2]:
        route_table.associate_with_subnet(SubnetId=subnet.id)
        ec2_client.modify_subnet_attribute(SubnetId=subnet.id, MapPublicIpOnLaunch={"Value": True})

    print(f"Subnets created: {subnet1.id}, {subnet2.id}")
    return [subnet1.id, subnet2.id]

def create_security_group(vpc):
    print("Creating Security Group (HTTP, SSH)...")
    sg = ec2.create_security_group(
        GroupName=f"{PROJECT_NAME}-sg",
        Description="Allow SSH and HTTP",
        VpcId=vpc.id
    )

    sg.authorize_ingress(
        IpPermissions=[
            {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
            {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
        ]
    )
    print(f"Security Group created: {sg.id}")
    return sg

def create_key_pair():
    print("Creating Key Pair...")
    keypair = ec2_client.create_key_pair(KeyName=KEY_NAME)
    with open(KEY_PATH, "w") as file:
        file.write(keypair['KeyMaterial'])
    os.chmod(KEY_PATH, 0o400)
    print(f"Key saved: {KEY_PATH}")
    return KEY_NAME

def create_launch_template(sg_id, key_name):
    print("Creating Launch Template...")
    lt = ec2_client.create_launch_template(
        LaunchTemplateName=f"{PROJECT_NAME}-lt",
        LaunchTemplateData={
            'ImageId': AMI_ID,
            'InstanceType': INSTANCE_TYPE,
            'KeyName': key_name,
            'SecurityGroupIds': [sg_id],
            'UserData': """#!/bin/bash
            yum update -y
            yum install -y httpd
            systemctl start httpd
            systemctl enable httpd
            echo '<h1>Welcome to Vijay Backend Server</h1>' > /var/www/html/index.html
            """
        }
    )
    print(f"Launch Template created: {lt['LaunchTemplate']['LaunchTemplateId']}")
    return lt['LaunchTemplate']['LaunchTemplateId']

def create_launch_template(sg_id, key_name):
    print("Creating Launch Template...")

    # Define a simple user data script
    user_data_script = """#!/bin/bash
    sudo apt update -y
    sudo apt install -y nginx
    sudo systemctl start nginx
    sudo systemctl enable nginx
    echo '<h1>Hello from Auto Scaling Group via Boto3!</h1>' > /var/www/html/index.html
    """

    # Encode user data in base64 as required by AWS
    encoded_user_data = base64.b64encode(user_data_script.encode("utf-8")).decode("utf-8")

    lt = ec2_client.create_launch_template(
        LaunchTemplateName=f"{PROJECT_NAME}-lt",
        LaunchTemplateData={
            "ImageId": "ami-004e960cde33f9146",   # ✅ your Ubuntu AMI ID
            "InstanceType": "t2.micro",
            "KeyName": key_name,
            "SecurityGroupIds": [sg_id],
            "UserData": encoded_user_data,        # ✅ correctly encoded
        },
        VersionDescription="v1"
    )

    lt_id = lt["LaunchTemplate"]["LaunchTemplateId"]
    print(f"Created Launch Template {lt_id}")
    return lt_id


def create_auto_scaling_group(lt_id, subnet_ids):
    print("Creating Auto Scaling Group...")
    asg_name = f"{PROJECT_NAME}-asg"
    asg_client.create_auto_scaling_group(
        AutoScalingGroupName=asg_name,
        LaunchTemplate={'LaunchTemplateId': lt_id, 'Version': '$Latest'},
        MinSize=1,
        MaxSize=2,
        DesiredCapacity=1,
        VPCZoneIdentifier=",".join(subnet_ids)
    )
    print(f"Auto Scaling Group created: {asg_name}")
    return asg_name

def create_load_balancer_and_target_group(vpc_id, subnet_ids, sg_id):
    print("Creating Application Load Balancer (ALB)...")

    alb = elbv2_client.create_load_balancer(
        Name=f"{PROJECT_NAME}-alb",
        Subnets=subnet_ids,
        SecurityGroups=[sg_id],
        Scheme='internet-facing',
        Type='application',
        IpAddressType='ipv4'
    )
    alb_arn = alb['LoadBalancers'][0]['LoadBalancerArn']

    tg = elbv2_client.create_target_group(
        Name=f"{PROJECT_NAME}-tg",
        Protocol='HTTP',
        Port=80,
        VpcId=vpc_id,
        TargetType='instance'
    )
    tg_arn = tg['TargetGroups'][0]['TargetGroupArn']

    listener = elbv2_client.create_listener(
        LoadBalancerArn=alb_arn,
        Protocol='HTTP',
        Port=80,
        DefaultActions=[{'Type': 'forward', 'TargetGroupArn': tg_arn}]
    )
    listener_arn = listener['Listeners'][0]['ListenerArn']

    print(f"ALB created: {alb_arn}")
    print(f"Target Group created: {tg_arn}")
    print(f"Listener created: {listener_arn}")

    return alb_arn, tg_arn, listener_arn

# === Main ===
def main():
    print("🚀 Starting AWS Infra Creation...")
    vpc, route_table = create_vpc()
    subnet_ids = create_public_subnets(vpc, route_table)
    sg = create_security_group(vpc)
    key_name = create_key_pair()
    lt_id = create_launch_template(sg.id, key_name)
    asg_name = create_auto_scaling_group(lt_id, subnet_ids)
    alb_arn, tg_arn, listener_arn = create_load_balancer_and_target_group(vpc.id, subnet_ids, sg.id)
    print("\n✅ Infrastructure successfully created!")
    print(f"VPC: {vpc.id}\nSubnets: {subnet_ids}\nSG: {sg.id}\nASG: {asg_name}\nALB: {alb_arn}")

if __name__ == "__main__":
    main()
