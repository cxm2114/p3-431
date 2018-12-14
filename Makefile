SOURCES = newfile.py 
OUT = out
default:
	python 431-P3.py InputSamples/infile.sample.txt
ex1:
	python newfile.py InputSamples/ex1.txt
ex2:
	python newfile.py InputSamples/ex2.txt
ex3:
	python newfile.py InputSamples/ex3.txt
ex4:
	python newfile.py InputSamples/ex4.txt
clean:
	rm pipeline* 
