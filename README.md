# Schedule-Generator-Application
An automated shift scheduling and generating application using Google OR API Tools, written in Python. 
This application makes use of constraint and linear programming.

###### Main branch is protected, pull-requests require the approval of one user before merging to Main ######
###### DB Credentials required from admin

VERSION 1.0 (21-08-2024):
- The application takes users and shifts, runs them through the Google OR Solver, applies the relevent constraints and creates assignments. 
- Schedules are then generated automatically for every 2 months (at specific months). -> using a scheduled cron job (APScheduler)
- It will generate based on the current month that the generation code is run.
- The application also checks the db before generating to prevent duplicated generation. 
- If there is an issue with automatic generation, schedules can be generated manually by running the frontend locally, selecting the start date and clicking 'generate schedule'.

- Important to note**: the solver is not completely accurate, as there are alot of set constraints to fulfill. It is prone to throwing outliers that don't make sense/fulfill every constraint. This is mainly due to the solver trying to mathematically balance the number of users to shift slots as well as attempting to apply the constrints to every user. In this version, if more constraints are added to its current state, it is usually unable to find a feasible solution. 

# Scheduling Constraints 
- We have 4 shift slots being 6am-2pm, 8am-4pm, 2pm-10pm, 10pm-6am 
- These shifts run every day of the week(Monday-Sunday).  
- Each user follows constraints of never working more than 3 consecutive days in a row without a 2 day break. If it is not possible to give every employee 2 consecutive days off in a row then the rest days can be split. 
- In total between Monday and Sunday each user should have worked 5 days total and rested for 2.
- If the previous shift ended at 6am (10pm-6am shift), they can only work another 10pm-6am or their rest days can begin. 
- If the previous shift ended at 10pm (2pm-10pm shift), they can only work another 2pm-10pm or their rest days can begin as well. 


# Set-Up Environment
1. Open Terminal and set up virtual environment:
python -m venv venv

2. Activate virtual environment:
venv\Scripts\activate

3. Install Required Packages:
pip install -r requirements.txt

4. Create a .env file in your root directory with the relevent Database Connection Credentials

# Running the Backend
1. Activate virtual environment -> venv\Scripts\activate
2. python app.py

# Running Frontend (For Manual generation)
1. http://localhost:5000/ 

# Google OR Tools Set-Up
https://developers.google.com/optimization/service/setup

