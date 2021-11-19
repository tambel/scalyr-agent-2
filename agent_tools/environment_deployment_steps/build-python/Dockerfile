FROM centos:6 as base

ADD ./CentOS-Base.repo /etc/yum.repos.d/CentOS-Base.repo
RUN yum upgrade -y
RUN yum install -y wget tar
RUN echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf
RUN ldconfig

FROM base as build-base-old-gcc
RUN yum groupinstall -y 'Development Tools'




FROM build-base-old-gcc as build-gcc
RUN wget http://mirrors.kernel.org/gnu/gcc/gcc-5.5.0/gcc-5.5.0.tar.gz
RUN tar -zxvf gcc-5.5.0.tar.gz
WORKDIR gcc-5.5.0
RUN ./contrib/download_prerequisites

WORKDIR /build-gcc
RUN ../gcc-5.5.0/configure --disable-multilib
RUN make "-j$(nproc)"
RUN make install

FROM build-base-old-gcc as build-base
RUN yum remove -y gcc
COPY --from=build-gcc /usr/local /usr/local

FROM build-base as build-openssl
WORKDIR /source
RUN wget https://github.com/openssl/openssl/archive/refs/tags/OpenSSL_1_1_1k.tar.gz
RUN tar -xvf OpenSSL_1_1_1k.tar.gz
WORKDIR /build-openssl
RUN /source/openssl-OpenSSL_1_1_1k/Configure linux-x86_64 shared
RUN make "-j$(nproc)"
RUN make install


FROM build-base as build-python
COPY --from=build-openssl /usr/local /usr/local
WORKDIR /
RUN yum install -y zlib-devel bzip2 bzip2-devel readline-devel tk-devel libffi-devel xz-devel
RUN git clone --depth 1 --branch v2.2.0 git://github.com/pyenv/pyenv.git .pyenv
RUN ls .pyenv/plugins/python-build/bin
RUN PYTHON_CONFIGURE_OPTS="--with-openssl=/usr/local --enable-shared" PYTHON_MAKE_OPTS="-j$(nproc)" .pyenv/plugins/python-build/bin/python-build 3.8.10 /usr/local -v

#FROM base as base-python
#COPY --from=build-python /usr/local /usr/local
#RUN ldconfig


FROM build-base as build-rust
COPY --from=build-python /usr/local /usr/local

WORKDIR /source
RUN curl https://ftp.gnu.org/gnu/binutils/binutils-2.37.tar.gz > binutils-2.37.tar.gz
RUN tar -xvf binutils-2.37.tar.gz
WORKDIR binutils-2.37
RUN ./configure
RUN make "-j$(nproc)"
RUN make install
RUN rpm -e --nodeps binutils

WORKDIR /source
RUN yum remove -y cmake
RUN wget https://github.com/Kitware/CMake/releases/download/v3.21.4/cmake-3.21.4-linux-x86_64.tar.gz
RUN tar -xvf cmake-3.21.4-linux-x86_64.tar.gz
RUN cp -a cmake-3.21.4-linux-x86_64/. /usr/local

WORKDIR /source
RUN git clone --branch v1.10.2 git://github.com/ninja-build/ninja.git
WORKDIR ninja
RUN ./configure.py --bootstrap
RUN cp ./ninja /usr/local/bin

WORKDIR /source
RUN git clone --depth 1 --branch 1.56.1 https://github.com/rust-lang/rust.git

WORKDIR rust
RUN git submodule update --init --recursive
ADD config.toml config.toml
RUN ./x.py build
RUN ./x.py install
RUN ./x.py install cargo

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