FROM ubuntu:20.04 as stage

WORKDIR /opt
RUN apt-get update && apt-get install -q -y --no-install-recommends \
	git \
	ca-certificates \
    && rm -rf /var/lib/apt/lists/*


LABEL VERSION="07.14.2021"
WORKDIR /
ARG username
ARG password
#build container with: docker build -t --build-arg username=Username --build-arg password=password local/avid-base:0.1.0
RUN git clone https://"$username":"$password"@phabricator.mitk.org/diffusion/AVID/avid.git ./avid-src  && \
    cd avid-src  &&\
	git checkout master # origin/T22565-GeneralizeBatchActions
################################################################################################################################
###################################################### Second Stage #########################################################
################################################################################################################################
FROM ubuntu:20.04

RUN apt-get update && apt-get install -q -y --no-install-recommends \
	python3 \
	python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --upgrade pip

WORKDIR /
COPY files/requirements.txt /
RUN pip3 install --no-cache-dir -r requirements.txt


COPY --from=stage /avid-src ./avid-src

RUN cd avid-src && \
	python3 setup.py develop

