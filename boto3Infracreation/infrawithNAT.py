#!/usr/bin/env python3
"""
full_infra_with_nat.py
End-to-end infra creation (eu-central-1) with NAT Gateway, ALB, ASG, Launch Template.
CIDR: 10.201.0.0/16

Run: python full_infra_with_nat.py
"""

import boto3
import botocore
import base64
import time
import sys

# ---------------- CONFIG ----------------
REGION = "eu-central-1"
PROJECT = "vijay-fullstack-nat"
VPC_CIDR = "10.201.0.0/16"

# public subnets (AZ suffixes will be appended; ensure chosen AZs exist in your region)
PUBLIC_SUBNET_CIDRS = ["10.201.1.0/24", "10.201.2.0/24"]
PRIVATE_SUBNET_CIDRS = ["10.201.101.0/24", "10.201.102.0/24"]

AMI_ID = "ami-04e601abe3e1a910f"   # <-- Example Amazon Linux 2 AMI for eu-central-1 (replace if you prefer)
INSTANCE_TYPE = "t3.medium"

KEY_NAME = f"{PROJECT}-key"
PEM_PATH = f"./{KEY_NAME}.pem"

ASG_NAME = f"{PROJECT}-asg"
LAUNCH_TEMPLATE_NAME = f"{PROJECT}-lt"
ALB_NAME = f"{PROJECT}-alb"
TG_NAME = f"{PROJECT}-tg"

MIN_SIZE = 3
DESIRED_CAPACITY = 5
MAX_SIZE = 5
# ----------------------------------------

# Clients / Resources
session = boto3.Session(region_name=REGION)
ec2 = session.resource("ec2")
ec2_client = session.client("ec2")
elbv2 = session.client("elbv2")
autoscaling = session.client("autoscaling")

# Utility
def choose_azs():
    azs = [az['ZoneName'] for az in ec2_client.describe_availability_zones()['AvailabilityZones']]
    # pick first two AZs (safe default)
    return azs[0:2]

# --------------- Create / Reuse VPC ---------------
def create_vpc():
    print("Creating VPC...")
    # try to create a VPC; if too many VPCs exist, reuse one
    try:
        vpc = ec2.create_vpc(CidrBlock=VPC_CIDR)
        vpc.wait_until_available()
        vpc.create_tags(Tags=[{"Key":"Name","Value":f"{PROJECT}-vpc"}])
        print(f"Created VPC: {vpc.id}")
        return vpc
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'VpcLimitExceeded':
            print("VpcLimitExceeded: looking for an existing VPC to reuse...")
            # pick the first VPC in this account/region that's not default
            vpcs = list(ec2.vpcs.filter(Filters=[{"Name":"isDefault","Values":["false"]}]))
            if vpcs:
                print(f"Reusing existing VPC {vpcs[0].id}")
                return vpcs[0]
            else:
                raise
        else:
            raise

# --------------- IGW + Route Table ---------------
def create_igw_and_route_table(vpc):
    print("Creating and attaching Internet Gateway...")
    igw = ec2.create_internet_gateway()
    igw.attach_to_vpc(VpcId=vpc.id)
    ec2_client.create_tags(Resources=[igw.id], Tags=[{"Key":"Name","Value":f"{PROJECT}-igw"}])
    print(f"Attached IGW: {igw.id}")

    print("Creating public route table and default route to IGW...")
    pub_rt = vpc.create_route_table()
    pub_rt.create_tags(Tags=[{"Key":"Name","Value":f"{PROJECT}-public-rt"}])
    pub_rt.create_route(DestinationCidrBlock="0.0.0.0/0", GatewayId=igw.id)
    print(f"Created public route table: {pub_rt.id}")
    return igw, pub_rt

# --------------- Subnets ---------------
def create_subnets(vpc, pub_rt, azs):
    print("Creating public and private subnets across AZs:", azs)
    public_subnet_ids = []
    private_subnet_ids = []

    for idx, az in enumerate(azs):
        pub_cidr = PUBLIC_SUBNET_CIDRS[idx]
        priv_cidr = PRIVATE_SUBNET_CIDRS[idx]

        pub_sub = ec2.create_subnet(VpcId=vpc.id, CidrBlock=pub_cidr, AvailabilityZone=az)
        ec2_client.modify_subnet_attribute(SubnetId=pub_sub.id, MapPublicIpOnLaunch={"Value": True})
        ec2_client.create_tags(Resources=[pub_sub.id], Tags=[{"Key":"Name","Value":f"{PROJECT}-pub-{az}"}])
        pub_rt.associate_with_subnet(SubnetId=pub_sub.id)
        public_subnet_ids.append(pub_sub.id)

        priv_sub = ec2.create_subnet(VpcId=vpc.id, CidrBlock=priv_cidr, AvailabilityZone=az)
        ec2_client.create_tags(Resources=[priv_sub.id], Tags=[{"Key":"Name","Value":f"{PROJECT}-priv-{az}"}])
        private_subnet_ids.append(priv_sub.id)

        print(f"Created public {pub_sub.id} ({pub_cidr}) and private {priv_sub.id} ({priv_cidr}) in {az}")

    return public_subnet_ids, private_subnet_ids

# --------------- NAT Gateway & Private Route Table ---------------
def create_nat_and_private_route(public_subnet_id, vpc):
    print("Allocating Elastic IP for NAT Gateway...")
    eip = ec2_client.allocate_address(Domain='vpc')
    alloc_id = eip['AllocationId']
    print(f"EIP allocated: {alloc_id}")

    print("Creating NAT Gateway in public subnet:", public_subnet_id)
    nat_resp = ec2_client.create_nat_gateway(SubnetId=public_subnet_id, AllocationId=alloc_id)
    nat_id = nat_resp['NatGateway']['NatGatewayId']
    print(f"NAT Gateway created: {nat_id} (waiting for available)")

    # Wait until NAT is available (can take a minute)
    waiter = ec2_client.get_waiter('nat_gateway_available')
    waiter.wait(NatGatewayIds=[nat_id])
    print("NAT Gateway is now available.")

    # Create a private route table and route to NAT
    print("Creating private route table and route to NAT...")
    priv_rt = vpc.create_route_table()
    ec2_client.create_tags(Resources=[priv_rt.id], Tags=[{"Key":"Name","Value":f"{PROJECT}-private-rt"}])
    priv_rt.create_route(DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat_id)
    print(f"Created private route table {priv_rt.id} -> NAT {nat_id}")
    return nat_id, priv_rt.id

# --------------- Security Groups ---------------
def create_security_groups(vpc):
    print("Creating Security Groups...")
    # ALB SG - allow inbound HTTP from anywhere
    alb_sg = ec2.create_security_group(GroupName=f"{PROJECT}-alb-sg", Description="ALB security group", VpcId=vpc.id)
    alb_sg.authorize_ingress(IpPermissions=[
        {'IpProtocol':'tcp','FromPort':80,'ToPort':80,'IpRanges':[{'CidrIp':'0.0.0.0/0'}]},
    ])
    ec2_client.create_tags(Resources=[alb_sg.id], Tags=[{"Key":"Name","Value":"alb-sg"}])
    print(f"ALB SG: {alb_sg.id}")

    # EC2 SG - allow inbound HTTP from ALB SG, allow SSH from anywhere (consider restricting)
    ec2_sg = ec2.create_security_group(GroupName=f"{PROJECT}-ec2-sg", Description="EC2 security group", VpcId=vpc.id)
    # Allow HTTP from ALB SG (use security-group id)
    ec2_sg.authorize_ingress(IpPermissions=[
        {'IpProtocol':'tcp','FromPort':80,'ToPort':80,'UserIdGroupPairs':[{'GroupId':alb_sg.id}]},
        {'IpProtocol':'tcp','FromPort':22,'ToPort':22,'IpRanges':[{'CidrIp':'0.0.0.0/0'}]}
    ])
    ec2_client.create_tags(Resources=[ec2_sg.id], Tags=[{"Key":"Name","Value":"ec2-sg"}])
    print(f"EC2 SG: {ec2_sg.id}")

    return alb_sg.id, ec2_sg.id

# --------------- Key Pair ----------------
def create_keypair():
    print("Ensuring Key Pair exists...")
    try:
        # try create; if already exists we'll catch error
        resp = ec2_client.create_key_pair(KeyName=KEY_NAME)
        with open(PEM_PATH, "w") as f:
            f.write(resp['KeyMaterial'])
        # Set permission - may not work on Windows, user must ensure permission
        try:
            import os
            os.chmod(PEM_PATH, 0o400)
        except Exception:
            pass
        print(f"Key pair created and saved to {PEM_PATH}")
    except botocore.exceptions.ClientError as e:
        code = e.response['Error']['Code']
        if code == 'InvalidKeyPair.Duplicate':
            print("Key pair already exists in AWS — reusing it.")
        else:
            raise

# --------------- Launch Template ----------------
def create_launch_template(sg_id):
    print("Creating Launch Template (with base64-encoded user-data)...")
    # Use Amazon Linux 2 style userdata (httpd)
    userdata = """#!/bin/bash
yum update -y
yum install -y httpd
systemctl enable httpd
systemctl start httpd
echo "<h1>Healthy from $(hostname)</h1>" > /var/www/html/index.html
"""
    encoded_ud = base64.b64encode(userdata.encode("utf-8")).decode("utf-8")

    try:
        resp = ec2_client.create_launch_template(
            LaunchTemplateName=LAUNCH_TEMPLATE_NAME,
            LaunchTemplateData={
                "ImageId": AMI_ID,
                "InstanceType": INSTANCE_TYPE,
                "KeyName": KEY_NAME,
                "SecurityGroupIds": [sg_id],
                # If you want instances to *have* public IPs (for testing), uncomment NetworkInterfaces block.
                # For production behind ALB, keep instances private and use NAT for outbound.
                # "NetworkInterfaces": [
                #     {"DeviceIndex": 0, "AssociatePublicIpAddress": True, "Groups": [sg_id]}
                # ],
                "UserData": encoded_ud
            },
            VersionDescription="v1"
        )
        lt_id = resp['LaunchTemplate']['LaunchTemplateId']
        print(f"Created Launch Template: {lt_id}")
        return lt_id
    except botocore.exceptions.ClientError as e:
        code = e.response['Error']['Code']
        if code == 'InvalidLaunchTemplateName.AlreadyExistsException':
            # reuse existing
            resp = ec2_client.describe_launch_templates(LaunchTemplateNames=[LAUNCH_TEMPLATE_NAME])
            lt_id = resp['LaunchTemplates'][0]['LaunchTemplateId']
            print(f"Launch Template already exists, reusing: {lt_id}")
            return lt_id
        else:
            raise

# --------------- Auto Scaling Group ----------------
def create_auto_scaling_group(lt_id, private_subnet_ids, target_group_arn):
    print("Creating Auto Scaling Group and attaching Target Group...")
    try:
        autoscaling.create_auto_scaling_group(
            AutoScalingGroupName=ASG_NAME,
            LaunchTemplate={'LaunchTemplateId': lt_id, 'Version': '$Latest'},
            MinSize=MIN_SIZE,
            MaxSize=MAX_SIZE,
            DesiredCapacity=DESIRED_CAPACITY,
            VPCZoneIdentifier=",".join(private_subnet_ids),
            TargetGroupARNs=[target_group_arn],
            Tags=[{'Key':'Name','Value':f"{PROJECT}-instance",'PropagateAtLaunch':True}]
        )
        print(f"Created ASG: {ASG_NAME}")
    except botocore.exceptions.ClientError as e:
        code = e.response['Error']['Code']
        if code == 'AlreadyExists':
            print(f"ASG {ASG_NAME} already exists, skipping creation.")
        else:
            raise

# --------------- ALB, Target Group, Listener ---------------
def create_alb_and_tg(public_subnet_ids, vpc_id, alb_sg_id):
    print("Creating ALB in public subnets...")
    alb_resp = elbv2.create_load_balancer(
        Name=ALB_NAME,
        Subnets=public_subnet_ids,
        SecurityGroups=[alb_sg_id],
        Scheme='internet-facing',
        Type='application',
        IpAddressType='ipv4'
    )
    alb_arn = alb_resp['LoadBalancers'][0]['LoadBalancerArn']
    alb_dns = alb_resp['LoadBalancers'][0]['DNSName']
    print(f"ALB created: {alb_arn} (DNS: {alb_dns})")

    print("Creating Target Group...")
    tg_resp = elbv2.create_target_group(
        Name=TG_NAME,
        Protocol='HTTP',
        Port=80,
        VpcId=vpc_id,
        TargetType='instance',
        HealthCheckProtocol='HTTP',
        HealthCheckPath='/',
        HealthCheckIntervalSeconds=15,
        Matcher={'HttpCode':'200'}
    )
    tg_arn = tg_resp['TargetGroups'][0]['TargetGroupArn']
    print(f"Target Group created: {tg_arn}")

    print("Creating Listener (HTTP :80)...")
    listener = elbv2.create_listener(
        LoadBalancerArn=alb_arn,
        Protocol='HTTP',
        Port=80,
        DefaultActions=[{'Type':'forward','TargetGroupArn':tg_arn}]
    )
    listener_arn = listener['Listeners'][0]['ListenerArn']
    print(f"Listener created: {listener_arn}")

    return alb_arn, alb_dns, tg_arn, listener_arn

# --------------- MAIN FLOW ---------------
def main():
    azs = choose_azs()
    if len(azs) < 2:
        print("ERROR: Not enough AZs returned for region. Exiting.")
        sys.exit(1)

    # VPC
    vpc = create_vpc()

    # IGW + public route table
    igw, pub_rt = create_igw_and_route_table(vpc)

    # Subnets
    public_subnet_ids, private_subnet_ids = create_subnets(vpc, pub_rt, azs)

    # NAT gateway in first public subnet -> create private route table(s)
    nat_id, private_rt_id = create_nat_and_private_route(public_subnet_ids[0], vpc)

    # Associate private route table with private subnets
    for sid in private_subnet_ids:
        ec2_client.associate_route_table(RouteTableId=private_rt_id, SubnetId=sid)
    print("Associated private route table with private subnets.")

    # Security groups
    alb_sg_id, ec2_sg_id = create_security_groups(vpc)

    # Key pair
    create_keypair()

    # Launch template (instances will be private; NAT provides outbound internet)
    lt_id = create_launch_template(ec2_sg_id)

    # Create ALB and TG in public subnets
    alb_arn, alb_dns, tg_arn, listener_arn = create_alb_and_tg(public_subnet_ids, vpc.id, alb_sg_id)

    # ASG in private subnets with TargetGroup attached (ASG will register instances with TG)
    create_auto_scaling_group(lt_id, private_subnet_ids, tg_arn)

    print("\n=== Completed ===")
    print(f"VPC: {vpc.id}")
    print(f"Public Subnets: {public_subnet_ids}")
    print(f"Private Subnets: {private_subnet_ids}")
    print(f"IGW: {igw.id}")
    print(f"NAT Gateway: {nat_id}")
    print(f"Private RouteTable: {private_rt_id}")
    print(f"ALB DNS: {alb_dns}")
    print(f"Target Group ARN: {tg_arn}")
    print(f"ASG Name: {ASG_NAME}")
    print("\nNotes:\n - If instances appear 'initial' for health checks, wait ~1-2 minutes for userdata to complete.\n - For SSH access to instances keep them private (recommended) and use a bastion host in public subnet if needed.\n")

if __name__ == "__main__":
    main()
