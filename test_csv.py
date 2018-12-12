import csv
from math import *
out_pipe_list=[]
#out_pipe_list.append([0,0,0,0,0,0])
print(out_pipe_list)
#rename function
def rename (cur_inst):
    if 'R' in cur_inst:
        if len(empty_list) >=3:
            cur_inst[1] = empty_list.pop(0);
            cur_inst[2] = empty_list.pop(0);
            cur_inst[3] = empty_list.pop(0);
            issue_q.append(cur_inst)
            return 1;
        #out_pipe_list.append(issu_num, issue_num + 1, )
        else:
            return 0;

    elif 'I' in cur_inst:
        if len(empty_list) >=2:
            cur_inst[1] = empty_list.pop(0);
            cur_inst[2] = empty_list.pop(0);
            #cur_inst[3] = empty_list.pop(0);
            issue_q.append(cur_inst)
            return 1;
        else:
            return 0;

    elif 'L' in cur_inst:
        if len(empty_list) >=2:
            cur_inst[1] = empty_list.pop(0);
            #cur_inst[2] = empty_list.pop(0);
            cur_inst[3] = empty_list.pop(0);
            issue_q.append(cur_inst)
            return 1;
        else:
            return 0;

    elif 'S' in cur_inst:
        if len(empty_list) >=2:
            cur_inst[1] = empty_list.pop(0);
            #cur_inst[2] = empty_list.pop(0);
            cur_inst[3] = empty_list.pop(0);
            issue_q.append(cur_inst)
            return 1;
        else:
            return 0;


with open('inst.csv', newline='') as csvfile:
    data = list(csv.reader(csvfile))

#number of physical register
num_phy_reg=(data[0][0])
phy_reg=int(num_phy_reg)

#issue width
num_issue_width=data[0][1]
issue_width=int(data[0][1])

#total instruction count
inst_count = (len(data))
num_issues = ceil((inst_count - 1)/issue_width)

#create an empty physical register file
empty_list = []
for i in range (1, phy_reg + 1):
    empty_list.append(i)

#create an empty issue queue
current_issue = 1;
issue_q = [];

#rename all the instruction in the present issue
while (current_issue <=num_issues):
    for i in range ((current_issue-1)*issue_width, current_issue*issue_width 
            if  current_issue*issue_width < len(data) else len(data)):
        if rename(data[i]) == 1:
            #rename all instructions in the present issue
            out_pipe_list.append([current_issue-1,current_issue,current_issue + 1,
                current_issue + 2,
                current_issue + 3,
                current_issue + 4,
                current_issue + 5])

    current_issue += 1;

################################################## DEBUG ##################################################  
print(issue_q)
print(empty_list)
print(out_pipe_list)
#while (current_issue <= num_issues):t_issue <= num_issues):
