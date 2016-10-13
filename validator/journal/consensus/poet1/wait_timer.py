# Copyright 2016 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------------

import logging
import time

from gossip.common import NullIdentifier

LOGGER = logging.getLogger(__name__)


class WaitTimerError(Exception):
    pass


class WaitTimer(object):
    """Wait timers represent a random duration incorporated into a wait
    certificate.

    Attributes:
        WaitTimer.minimum_wait_time (float): The minimum wait time in seconds.
        WaitTimer.target_wait_time (float): The target wait time in seconds.
        WaitTimer.initial_wait_time (float): The initial wait time in seconds.
        WaitTimer.certificate_sample_length (int): The number of certificates
            to sample for the population estimate.
        WaitTimer.fixed_duration_blocks (int): If fewer than
            WaitTimer.fixed_duration_blocks exist, then base the local mean
            on a ratio based on InitialWaitTime, rather than the history.
        WaitTimer.poet_enclave (module): The PoetEnclave module to use for
            executing enclave functions.
        previous_certificate_id (str): The id of the previous certificate.
        local_mean (float): The local mean wait time based on the history of
            certs.
        request_time (float): The request time.
        duration (float): The duration of the wait timer.
        signature (str): The signature of the timer.

    """
    minimum_wait_time = 1.0
    target_wait_time = 30.0
    initial_wait_time = 3000.0
    certificate_sample_length = 50
    fixed_duration_blocks = certificate_sample_length

    poet_enclave = None

    @classmethod
    def _population_estimate(cls, certificates):
        """Estimates the size of the validator population by computing
        the average wait time and the average local mean used by
        the winning validator.

        Since the entire population should be computing from the same
        local mean based on history of certificates and we know that
        the minimum value drawn from a population of size N of
        exponentially distributed variables will be exponential with
        mean being 1 / N, we can estimate the population size from the
        ratio of local mean to global mean. a longer list of
        certificates will provide a better estimator only if the
        population of validators is relatively stable.

        Note:

        See the section entitled "Distribution of the minimum of
        exponential random variables" in the page
        http://en.wikipedia.org/wiki/Exponential_distribution

        Args:
            certificates (list): Previously committed certificates,
                ordered newest to oldest
        """
        assert isinstance(certificates, list)
        assert len(certificates) >= cls.certificate_sample_length

        sum_means = 0
        sum_waits = 0
        for certificate in certificates[:cls.certificate_sample_length]:
            sum_waits += \
                certificate.duration - cls.poet_enclave.MINIMUM_WAIT_TIME
            sum_means += certificate.local_mean

        avg_wait = sum_waits / len(certificates)
        avg_mean = sum_means / len(certificates)

        return avg_mean / avg_wait

    @classmethod
    def create_wait_timer(cls, certificates):
        """Creates a wait timer in the enclave and then constructs
        a WaitTimer object.

        Args:
            certificates (list): A historical list of certificates.

        Returns:
            journal.consensus.poet.wait_timer.WaitTimer: A new wait timer.
        """

        assert isinstance(certificates, list)

        previous_certificate_id = \
            certificates[-1].identifier if certificates else NullIdentifier
        local_mean = cls.compute_local_mean(certificates)

        # Create an enclave timer object and then use it to create a
        # WaitTimer object
        enclave_timer = \
            cls.poet_enclave.create_wait_timer(
                previous_certificate_id,
                local_mean)
        timer = cls(enclave_timer)

        LOGGER.info('wait timer created; %s', timer)

        return timer

    @classmethod
    def compute_local_mean(cls, certificates):
        """Computes the local mean wait time based on the certificate
        history.

        Args:
            certificates (list): A historical list of certificates.

        Returns:
            float: The local mean wait time.
        """
        assert isinstance(certificates, list)

        count = len(certificates)
        if count < cls.fixed_duration_blocks:
            ratio = 1.0 * count / cls.fixed_duration_blocks
            local_mean = \
                (cls.target_wait_time * (1 - ratio * ratio)) + \
                (cls.initial_wait_time * ratio * ratio)
        else:
            local_mean = \
                cls.target_wait_time * cls._population_estimate(certificates)

        return local_mean

    @property
    def enclave_wait_timer(self):
        return \
            self.poet_enclave.deserialize_wait_timer(
                self._serialized_timer,
                self.signature)

    def __init__(self, enclave_timer):
        self.previous_certificate_id =\
            str(enclave_timer.previous_certificate_id)
        self.local_mean = float(enclave_timer.local_mean)
        self.request_time = float(enclave_timer.request_time)
        self.duration = float(enclave_timer.duration)
        self.signature = str(enclave_timer.signature)

        # We cannot hold the timer because it cannot be pickled for storage
        # in the transaction block array
        self._serialized_timer = str(enclave_timer.serialize())

        self._expires = time.time() + self.duration + 0.1

    def __str__(self):
        return \
            'TIMER, {0:0.2f}, {1:0.2f}, {2}'.format(
                self.local_mean,
                self.duration,
                self.previous_certificate_id)

    def has_expired(self, now):
        """Determines whether the timer has expired.

        Args:
            now (float): The current time.

        Returns:
            bool: True if the timer has expired, false otherwise.
        """
        if now < self._expires:
            return False

        return self.poet_enclave.verify_wait_timer(self.enclave_wait_timer)


def set_wait_timer_globals(target_wait_time=None,
                           initial_wait_time=None,
                           certificate_sample_length=None,
                           fixed_duration_blocks=None,
                           minimum_wait_time=None):
    if target_wait_time is not None:
        WaitTimer.target_wait_time = float(target_wait_time)
    if initial_wait_time is not None:
        WaitTimer.initial_wait_time = float(initial_wait_time)
    if certificate_sample_length is not None:
        WaitTimer.certificate_sample_length = int(certificate_sample_length)
        WaitTimer.fixed_duration_blocks = int(certificate_sample_length)
    if fixed_duration_blocks is not None:
        WaitTimer.fixed_duration_blocks = int(fixed_duration_blocks)
    if minimum_wait_time is not None:
        WaitTimer.minimum_wait_time = float(minimum_wait_time)
