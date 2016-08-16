#       __     ___           __
#   ___/ /__  / _ \___  ____/ /_____ ____
#  / _  / _ \/ // / _ \/ __/  '_/ -_) __/
#  \_,_/\___/____/\___/\__/_/\_\\__/_/
#  doDocker (c) 2014-2016 Andreas Elvers
#  n@work Internet Informationssysteme GmbH
#
#  doDocker is based upon pydoit.org 

FROM debian:jessie
RUN apt-key adv --keyserver hkp://p80.pool.sks-keyservers.net:80 --recv-keys 58118E89F3A912897C070ADBF76221572C52609D
RUN echo deb http://apt.dockerproject.org/repo debian-jessie main >/etc/apt/sources.list.d/docker.list
RUN DEBIAN_FRONTEND=noninteractive \
    apt-get update && \
    apt-get -y --no-install-recommends install \
            docker-engine debootstrap busybox-static python-pip sudo curl
COPY . /dodocker
RUN pip install /dodocker
WORKDIR /build


