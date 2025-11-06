# Sample MERN with Microservices



For `helloService`, create `.env` file with the content:
```bash
PORT=3001
```

For `profileService`, create `.env` file with the content:
```bash
PORT=3002
MONGO_URL="specifyYourMongoURLHereWithDatabaseNameInTheEnd"
```

Finally install packages in both the services by running the command `npm install`.

<br/>
For frontend, you have to install and start the frontend server:

```bash
cd frontend
npm install
npm start
```

Note: This will run the frontend in the development server. To run in production, build the application by running the command `npm run build`

List of the steps followed to make this application containerized 

Assumption and steps to follow for make it dockerize/kubenets/helm charts then CI CD for the same.
1. using the mongo free cluster and use it details in the secret
2. create ECR reporsitory for this application : 
975050024946.dkr.ecr.eu-central-1.amazonaws.com/containerize-vijay-assignment/frontend
975050024946.dkr.ecr.eu-central-1.amazonaws.com/containerize-vijay-assignment/helloservice
975050024946.dkr.ecr.eu-central-1.amazonaws.com/containerize-vijay-assignment/profileservice

3. added docker file for all the three components as per teh need.
 Docker login steps need to automate in the CI becuase its need to done manually as of now 
 aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin 975050024946.dkr.ecr.eu-central-1.amazonaws.com


4. create the scripts to create the image and push it to the reposiroty
bash  build-and-push.sh 975050024946.dkr.ecr.eu-central-1.amazonaws.com/containerize-vijay-assignment latest vijay

 975050024946.dkr.ecr.eu-central-1.amazonaws.com/containerize-vijay-assignment/profileservice:latest
975050024946.dkr.ecr.eu-central-1.amazonaws.com/containerize-vijay-assignment/helloservice:latest
975050024946.dkr.ecr.eu-central-1.amazonaws.com/containerize-vijay-assignment/frontend:latest

ECR creation command need to add in this 

creating kubenerts manifest for the hello and profileservice
