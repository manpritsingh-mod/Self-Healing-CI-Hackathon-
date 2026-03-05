FROM jenkins/jenkins:lts

# Skip initial setup wizard
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false"

# Install plugins
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# Set admin user (default: admin/admin)
ENV JENKINS_USER=admin
ENV JENKINS_PASS=admin

USER jenkins
