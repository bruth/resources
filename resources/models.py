from datetime import datetime
from werkzeug.wrappers import Response
from werkzeug.http import http_date
from .http import codes, methods

# Convenience function for checking for existent, callable methods
usable = lambda x, y: callable(getattr(x, y, None))

# ## Resource Metaclass
# Sets up a few helper components for the `Resource` class.
class ResourceMetaclass(type):

    def __new__(cls, name, bases, attrs):

        # Create the new class as is to start. Subclass attributes can be
        # checked for in `attrs` and handled as necessary relative to the base
        # classes.
        new_cls = type.__new__(cls, name, bases, attrs)

        # If `allowed_methods` is not defined explicitly in attrs, this
        # could mean one of two things: that the user wants it to inherit
        # from the parent class (if exists) or for it to be set implicitly.
        # The more explicit (and flexible) behavior will be to not inherit
        # it from the parent class, therefore the user must explicitly
        # re-set the attribute.
        if 'allowed_methods' not in attrs or not new_cls.allowed_methods:
            allowed_methods = []

            for method in methods:
                if usable(new_cls, method.lower()):
                    allowed_methods.append(method)

        # If the attribute is defined in this subclass, ensure all methods that
        # are said to be allowed are actually defined and callable.
        else:
            allowed_methods = list(new_cls.allowed_methods)

            for method in allowed_methods:
                if not usable(new_cls, method.lower()):
                    raise ValueError('The {} method is not defined for the '
                        'resource {}'.format(method, new_cls.__name__))

        # If `GET` is not allowed, remove `HEAD` method.
        if 'GET' not in allowed_methods and 'HEAD' in allowed_methods:
            allowed_methods.remove('HEAD')

        new_cls.allowed_methods = tuple(allowed_methods)

        if not new_cls.supported_content_types:
            new_cls.supported_content_types = new_cls.supported_accept_types

        if not new_cls.supported_patch_types:
            new_cls.supported_patch_types = new_cls.supported_content_types

        return new_cls


# ## Resource
# Comprehensive ``Resource`` class which implements sensible request
# processing. The process flow is largely derived from Alan Dean's
# [status code activity diagram][0].
#
# ### Implementation Considerations
# [Section 2][1] of the HTTP/1.1 specification states:
#
# > The methods GET and HEAD MUST be supported by all general-purpose servers.
# > All other methods are OPTIONAL;
#
# The `HEAD` handler is already implemented on the `Resource` class, but
# requires the `GET` handler to be implemented. Although not required, the
# `OPTIONS` handler is also implemented.
#
# Response representations should follow the rules outlined in [Section 5.1][2].
#
# [Section 6.1][3] defines that `GET`, `HEAD`, `OPTIONS` and `TRACE` are
# considered _safe_ methods, thus ensure the implementation of these methods do
# not have any side effects. In addition to the safe methods, `PUT` and
# `DELETE` are considered _idempotent_ which means subsequent identical requests
# to the same resource does not result it different responses to the client.
#
# Request bodies on `GET`, `HEAD`, `OPTIONS`, and `DELETE` requests are
# ignored. The HTTP spec does not define any semantics surrounding this
# situtation.
#
# Typical uses of `POST` requests are described in [Section 6.5][4], but in most
# cases should be assumed by clients as _black box_, neither safe nor idempotent.
# If updating an existing resource, it is more appropriate to use `PUT`.
#
# [Section 7.2.1][5] defines that `GET`, `HEAD`, `POST`, and 'TRACE' should have
# a payload for status code of 200 OK. If not supplied, a different 2xx code may
# be more appropriate.
#
# [0]: http://code.google.com/p/http-headers-status/downloads/detail?name=http-headers-status%20v3%20draft.png
# [1]: http://tools.ietf.org/html/draft-ietf-httpbis-p2-semantics-18#section-2
# [2]: http://tools.ietf.org/html/draft-ietf-httpbis-p2-semantics-18#section-5.1
# [3]: http://tools.ietf.org/html/draft-ietf-httpbis-p2-semantics-18#section-6.1
# [4]: http://tools.ietf.org/html/draft-ietf-httpbis-p2-semantics-18#section-6.5
class Resource(object):

    __metaclass__ = ResourceMetaclass

    # ### Service Availability
    # Toggle this resource as unavailable. If `True`, the service
    # will be unavailable indefinitely. If an integer or datetime is
    # used, the `Retry-After` header will set. An integer can be used
    # to define a seconds delta from the current time (good for unexpected
    # downtimes). If a datetime is set, the number of seconds will be
    # calculated relative to the current time (good for planned downtime).
    unavailable = False

    # ### Allowed Methods
    # If `None`, the allowed methods will be determined based on the resource
    # methods define, e.g. `get`, `put`, `post`. A list of methods can be
    # defined explicitly to have not expose defined methods.
    allowed_methods = None

    # ### Request Rate Limiting
    # Enforce request rate limiting. Both `rate_limit_count` and
    # `rate_limit_seconds` must be defined and not zero to be active.
    # By default, the number of seconds defaults to 1 hour, but the count
    # is `None`, therefore rate limiting is not enforced.
    rate_limit_count = None
    rate_limit_seconds = 60 * 60

    # ### Max Request Entity Length
    # If not `None`, checks if the request entity body is too large to
    # be processed.
    max_request_entity_length = None

    # ### Require Conditional Request
    # If `True`, `PUT` and `PATCH` requests are required to have a conditional
    # header for verifying the operation applies to the current state of the
    # resource on the server. This must be used in conjunction with either
    # the `use_etags` or `use_last_modified` option to take effect.
    require_conditional_request = False

    # ### Use ETags
    # If `True`, the `ETag` header will be set on responses and conditional
    # requests are supported. This applies to _GET_, _HEAD_, _PUT_, _PATCH_
    # and _DELETE_ requests.
    use_etags = True

    # ### Use Last Modified
    # If `True`, the `Last-Modified` header will be set on responses and
    # conditional requests are supported. This applies to _GET_, _HEAD_, _PUT_,
    # _PATCH_ and _DELETE_ requests.
    use_last_modified = False

    # ### Supported _Accept_ Mimetypes
    # Define a list of mimetypes supported for encoding response entity
    # bodies. Default to `('application/json',)`
    # _See also: `supported_content_types`_
    supported_accept_types = ('application/json',)

    # ### Supported _Content-Type_ Mimetypes
    # Define a list of mimetypes supported for decoding request entity bodies.
    # This is independent of the mimetypes encoders for request bodies.
    # Defaults to mimetypes defined in `supported_accept_types`.
    supported_content_types = None

    # ### Supported PATCH Mimetypes
    # Define a list of mimetypes supported for decoding request entity bodies
    # for `PATCH` requests. Defaults to mimetypes defined in
    # `supported_content_types`.
    supported_patch_types = None


    # ## Initialize Once, Process Many
    # Every `Resource` class can be initialized once since they are stateless
    # (and thus thread-safe).
    def __call__(self, request, *args, **kwargs):

        # Initilize a new response for this request. Passing the response along
        # the request cycle allows for gradual modification of the headers.
        response = Response()

        # Process the request, this should modify the `response`
        output = self.process(request, response, *args, **kwargs)

        if output is not None:
            response.data = output

        return response

    # ## Request Programatically
    # For composite resources, `resource.apply` can be used on related resources
    # with the original `request`.
    def apply(self, request, *args, **kargs):
        pass

    def process(self, request, response, *args, **kwargs):
        # TODO keep track of a list of request headers used to
        # determine the resource representation for the 'Vary'
        # header.

        # ### 503 Service Unavailable
        # The server does not need to be unavailable for a resource to be
        # unavailable...
        if self.check_service_unavailable(request, response):
            response.status = codes.service_unavailable
            return

        # ### 414 Request URI Too Long _(not implemented)_
        # This should be be handled upstream by the Web server

        # ### 400 Bad Request _(not implemented)_
        # Note that many services respond with this code when entities are
        # unprocessable. This should really be a 422 Unprocessable Entity

        # ### 401 Unauthorized
        # Check if the request is authorized to access this resource.
        if self.check_unauthorized(request, response):
            response.status = codes.unauthorized
            return

        # ### 403 Forbidden
        # Check if this resource is forbidden for the request.
        if self.check_forbidden(request, response):
            response.status = codes.forbidden
            return

        # ### 501 Not Implemented _(not implemented)_
        # This technically refers to a service-wide response for an
        # unimplemented request method.

        # ### 429 Too Many Requests
        # Both `rate_limit_count` and `rate_limit_seconds` must be none
        # falsy values to be checked.
        if self.rate_limit_count and self.rate_limit_seconds:
            if self.check_too_many_requests(request, response, *args, **kwargs):
                response.status = codes.too_many_requests
                return

        # ### Process an _OPTIONS_ request
        # Enough processing has been performed to allow an OPTIONS request.
        if request.method == methods.options and 'OPTIONS' in self.allowed_methods:
            return self.options(request, response)

        # ## Request Entity Checks
        # Only perform these checks if the request has supplied a body.
        if request.content_length:

            # ### 415 Unsupported Media Type
            # Check if the entity `Content-Type` supported for decoding.
            if self.check_unsupported_media_type(request, response):
                response.status = codes.unsupported_media_type
                return

            # ### 413 Request Entity Too Large
            # Check if the entity is too large for processing
            if self.max_request_entity_length:
                if self.check_request_entity_too_large(request, response):
                    response.status = codes.request_entity_too_large
                    return

        # ### 405 Method Not Allowed
        if self.check_method_not_allowed(request, response):
            response.status = codes.method_not_allowed
            return

        # ### 406 Not Acceptable
        # Checks Accept and Accept-* headers
        if self.check_not_acceptable(request, response):
            response.status = codes.not_acceptable
            return

        # ### 404 Not Found
        # Check if this resource exists.
        if self.check_not_found(request, response):
            response.status = codes.not_found
            return

        # ### 410 Gone
        # Check if this resource used to exist, but does not anymore.
        if self.check_gone(request, response, *args, **kwargs):
            response.status = codes.gone
            return

        # ### 428 Precondition Required
        # Prevents the "lost udpate" problem and requires client to confirm
        # the state of the resource has not changed since the last `GET`
        # request. This applies to `PUT` and `PATCH` requests.
        if self.require_conditional_request:
            if request.method == methods.put or request.method == methods.patch:
                if self.check_precondition_required(request, response, *args, **kwargs):
                    # HTTP/1.1
                    response.headers['Cache-Control'] = 'no-cache'
                    # HTTP/1.0
                    response.headers['Pragma'] = 'no-cache'
                    response.status = codes.precondition_required
                    return

        # ### 412 Precondition Failed
        # Conditional requests applies to GET, HEAD, PUT, and PATCH.
        # For GET and HEAD, the request checks the either the entity changed
        # since the last time it requested it, `If-Modified-Since`, or if the
        # entity tag (ETag) has changed, `If-None-Match`.
        if request.method == methods.put or request.method == methods.patch:
            if self.check_precondition_failed(request, response, *args, **kwargs):
                response.status = codes.precondition_failed
                return

        # Check for conditional GET or HEAD request
        if request.method == methods.get or request.method == methods.head:
            if self.use_etags and 'if-none-match' in request.headers:
                etag = self.get_etag(request, *args, **kwargs)
                if request.headers['if-none-match'] == etag:
                    response.status = codes.not_modified
                    return

            if self.use_last_modified and 'if-modified-since' in request.headers:
                modified = self.get_last_modified(request, *args, **kwargs)
                last_modified = http_date(modified)
                if request.headers['if-modified-since'] == last_modified:
                    response.status = codes.not_modified
                    return


        # ### Call Request Method Handler
        handler_output = getattr(self, request.method.lower())(request,
            response, *args, **kwargs)

        # TODO implement post request method handling header augmentation
        if self.use_etags and 'etag' not in response.headers:
            pass

        elif self.use_last_modified and 'last-modified' not in request.headers:
            pass

        return handler_output


    # ## Request Method Handlers
    # ### _HEAD_ Request Handler
    # Default handler for _HEAD_ requests. For this to be available,
    # a _GET_ handler must be defined.
    def head(self, request, response, *args, **kwargs):
        self.get(request, response, *args, **kwargs)
        response.data = ''

    # ### _OPTIONS_ Request Handler
    # Default handler _OPTIONS_ requests.
    def options(self, request, response, *args, **kwargs):
        # See [RFC 5789][0]
        # [0]: http://tools.ietf.org/html/rfc5789#section-3.1
        if 'PATCH' in self.allowed_methods:
            response.headers['Accept-Patch'] = ', '.join(self.supported_patch_types)

        response.headers['Allow'] = ', '.join(sorted(self.allowed_methods))
        response.headers['Content-Length'] = 0
        # HTTP/1.1
        response.headers['Cache-Control'] = 'no-cache'
        # HTTP/1.0
        response.headers['Pragma'] = 'no-cache'


    # ## Response Status Code Handlers
    # Each handler prefixed with `check_` corresponds to various client (4xx)
    # and server (5xx) error checking. For example, `check_not_found` will
    # return `True` if the resource does not exit. _Note: all handlers are
    # must return `True` to fail the check._

    # ### Service Unavailable
    # Checks if the service is unavailable based on the `unavailable` flag.
    # Set the `Retry-After` header if possible to inform clients when
    # the resource is expected to be available.
    # See also: `unavailable`
    def check_service_unavailable(self, request, response):
        if self.unavailable:
            if type(self.unavailable) is int and self.unavailable > 0:
                retry = self.unavailable
            elif type(self.unavailable) is datetime:
                retry = http_date(self.unavailable)
            else:
                retry = None

            if retry:
                response.headers['Retry-After'] = retry
            return True
        return False

    # ### Unauthorized
    # Checks if the request is authorized to access this resource.
    # Default is a no-op.
    def check_unauthorized(self, request, response):
        return False

    # ### Forbidden
    # Checks if the request is forbidden. Default is a no-op.
    def check_forbidden(self, request, response, *args, **kwargs):
        return False

    # ### Too Many Requests
    # Checks if this request is rate limited. Default is a no-op.
    def check_too_many_requests(self, request, response, *args, **kwargs):
        return False

    # ### Request Entity Too Large
    # Check if the request entity is too large to process.
    def check_request_entity_too_large(self, request, response):
        if request.content_length > self.max_request_entity_length:
            return True

    # ### Method Not Allowed
    # Check if the request method is not allowed.
    def check_method_not_allowed(self, request, response):
        if request.method not in self.allowed_methods:
            response.headers['Allow'] = ', '.join(sorted(self.allowed_methods))
            return True
        return False

    # ### Unsupported Media Type
    # Check if this resource can process the request entity body. Note
    # `Content-Type` is set as the empty string, so ensure it is not falsy
    # when processing it.
    def check_unsupported_media_type(self, request, response):
        if 'content-type' in request.headers and request.content_type:
            if not self.content_type_supported(request, response):
                return True

            if 'content-encoding' in request.headers:
                if not self.content_encoding_supported(request, response):
                    return True

            if 'content-language' in request.headers:
                if not self.content_language_supported(request, response):
                    return True

        return False

    # ### Not Acceptable
    # Check if this resource can return an acceptable response.
    def check_not_acceptable(self, request, response):
        if not self.accept_type_supported(request, response):
            return True

        if 'accept-language' in request.headers:
            if not self.accept_language_supported(request, response):
                return True

        if 'accept-charset' in request.headers:
            if not self.accept_charset_supported(request, response):
                return True

        if 'accept-encoding' in request.headers:
            if not self.accept_encoding_supported(request, response):
                return True

        return False

    # ### Precondition Required
    # Check if a conditional request is 
    def check_precondition_required(self, request, response, *args, **kwargs):
        if self.use_etags and 'if-match' not in request.headers:
            response.data = 'This request is required to be conditional; '\
                'try using "If-Match"'
            return True
        if self.use_last_modified and 'if-unmodified-since' not in request.headers:
            response.data = 'This request is required to be conditional; '\
                'try using "If-Unmodified-Since"'
            return True
        return False

    def check_precondition_failed(self, request, response, *args, **kwargs):
        # ETags are enabled. Check for conditional request headers. The current
        # ETag value is used for the conditional requests. After the request
        # method handler has been processed, the new ETag will be calculated.
        if self.use_etags and 'if-match' in request.headers:
            etag = self.get_etag(request, *args, **kwargs)
            if request.headers['if-match'] != etag:
                return True

        # Last-Modified date enabled. check for conditional request headers. The
        # current modification datetime value is used for the conditional
        # requests. After the request method handler has been processed, the new
        # Last-Modified datetime will be returned.
        if self.use_last_modified and 'if-unmodified-since' in request.headers:
            last_modified = self.get_last_modified(request, *args, **kwargs)
            if request.headers['if-unmodified-since'] != http_date(last_modified):
                return True

        return False


    # ### Not Found
    # Checks if the requested resource exists.
    def check_not_found(self, request, response, *args, **kwargs):
        return False

    # ### Gone
    # Checks if the resource _no longer_ exists.
    def check_gone(self, request, response, *args, **kwargs):
        return False



    # ## Request Accept-* handlers

    # Checks if the requested `Accept` mimetype is supported. Defaults
    # to using the first specified mimetype in `supported_accept_types`.
    def accept_type_supported(self, request, response):
        if 'accept' in request.headers:
            for mime in request.accept_mimetypes.values():
                if mime in self.supported_accept_types:
                    response._accept_type = mime
                    return True

            # Only if `Accept` explicitly contains a `*/*;q=0.0`
            # does it preclude from returning a non-matching mimetype.
            # This may be desirable behavior (or not), so add this as an
            # option, e.g. `force_accept_type`
            if not request.accept_mimetypes['*/*'] == 0:
                return False

        if len(self.supported_accept_types):
            response._accept_type = self.supported_accept_types[0]
        return True

    # Checks if the requested `Accept-Charset` is supported.
    def accept_charset_supported(self, request, response):
        return True

    # Checks if the requested `Accept-Encoding` is supported.
    def accept_encoding_supported(self, request, response):
        return True

    # Checks if the requested `Accept-Language` is supported.
    def accept_language_supported(self, request, response):
        return True


    # ## Conditionl Request Handlers

    # ### Calculate ETag
    # Calculates an etag for the requested entity.
    # Provides the client an entity tag for future conditional
    # requests.
    # For GET and HEAD requests the `If-None-Match` header may be
    # set to check if the entity has changed since the last request.
    # For PUT, PATCH, and DELETE requests, the `If-Match` header may be
    # set to ensure the entity is the same as the cllient's so the current
    # operation is valid (optimistic concurrency).
    def get_etag(self, request, *args, **kwargs):
        pass

    # ### Calculate Last Modified Datetime
    # Calculates the last modified time for the requested entity.
    # Provides the client the last modified of the entity for future
    # conditional requests.
    def get_last_modified(self, request, *args, **kwargs):
        pass

    # ### Calculate Expiry Datetime
    # Gets the expiry date and time for the requested entity.
    # Informs the client when the entity will be invalid. This is most
    # useful for clients to only refresh when they need to, otherwise the
    # client's local cache is used.
    def get_expiry(self, request, *args, **kwargs):
        pass


    # ## Entity Content-* handlers
    def content_type_supported(self, request, response, *args, **kwargs):
        return request.mimetype in self.supported_content_types

    def content_encoding_supported(self, request, response, *args, **kwargs):
        return True

    def content_language_supported(self, request, response, *args, **kwargs):
        return True
