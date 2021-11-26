FROM centos:7 as base

RUN yum install -y wget tar zlib-devel bzip2 bzip2-devel readline-devel tk-devel libffi-devel xz-devel
RUN yum groupinstall -y 'Development Tools'

WORKDIR /source
RUN wget https://github.com/openssl/openssl/archive/refs/tags/OpenSSL_1_1_1k.tar.gz
RUN tar -xvf OpenSSL_1_1_1k.tar.gz
WORKDIR /build-openssl
RUN /source/openssl-OpenSSL_1_1_1k/Configure linux-x86_64 shared
RUN make "-j$(nproc)"
RUN make install
RUN echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf
RUN ldconfig

WORKDIR /source
RUN git clone https://github.com/rbenv/ruby-build.git rbenv/plugins/ruby-build
RUN yum install -y zlib-devel
RUN PYTHON_CONFIGURE_OPTS="--with-openssl=/usr/local" rbenv/plugins/ruby-build/bin/ruby-build -v 2.7.3 /usr/local

WORKDIR /source
RUN git clone --depth 1 --branch v2.2.0 git://github.com/pyenv/pyenv.git .pyenv
RUN ls .pyenv/plugins/python-build/bin
RUN PYTHON_CONFIGURE_OPTS="--with-openssl=/usr/local --enable-shared" PYTHON_MAKE_OPTS="-j$(nproc)" .pyenv/plugins/python-build/bin/python-build 3.8.10 /usr/local -v


RUN gem install --no-document fpm -v 1.12.0
RUN gem cleanup

RUN yum clean all


#RUN yum install -y zlib-devel
#RUN ln -s /usr/local/bin/g++ /usr/local/bin/cc
#RUN CC='/usr/local/bin/g++' python3 -m pip install orjson
#RUN ln -s /usr/local/bin/g++ /usr/local/bin/cc
#RUN python3 -m pip install orjson




#FROM base
#RUN yum groupinstall -y 'Development Tools'
#RUN yum remove -y gcc
#COPY --from=build-rust /usr/local /usr/local
#COPY --from=build-ruby /usr/local /usr/local
#RUN yum install -y zlib-devel libc-devel
#RUN ln -s /usr/local/bin/g++ /usr/local/bin/cc
#RUN ldconfig
#RUN python3 -m pip install orjson

#

#
#WORKDIR /source/rust
#
#RUN ./x.py build -j 7
#RUN ./x.py install
#
#ENV PKG_CONFIG_PATH /usr/local/lib64/pkgconfig
#RUN ./x.py install cargo
#
#
#WORKDIR /
#ENV PATH="$HOME/.rbenv/bin:$PATH"
##RUN git clone https://github.com/rbenv/rbenv.git .rbenv
#RUN git clone git://github.com/sstephenson/ruby-build.git .rbenv/plugins/ruby-build
#
## Build and install ruby and fpm package.
#RUN .rbenv/plugins/ruby-build/bin/ruby-build 3.0.2 /usr/local
#
#
#WORKDIR /source
#RUN curl https://mirrors.edge.kernel.org/pub/software/scm/git/git-2.34.0.tar.gz > git-2.34.0.tar.gz
#RUN tar -xvf git-2.34.0.tar.gz
#WORKDIR git-2.34.0
#RUN ./configure
#RUN make -j6
#RUN yum remove -y git
#RUN make install
#
#RUN gem install --no-document fpm -v 1.12.0
#RUN gem cleanup
#
#RUN yum clean all
#

