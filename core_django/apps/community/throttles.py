from rest_framework.throttling import UserRateThrottle

class PostCreateThrottle(UserRateThrottle):
    """
    Giới hạn số lượng bài đăng (ForumPost) trong 1 ngày dựa trên gói tài khoản.
    Free: 3/day
    Plus: 10/day
    Pro: virtual unlimited
    """
    scope = 'post_create'

    def get_rate(self):
        # Trả về giá trị mặc định để tránh ImproperlyConfigured khi khởi tạo
        return '3/day'

    def allow_request(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return True

        tier = 'Free'
        # Check user's subscription tier
        if hasattr(request.user, 'subscription') and request.user.subscription.is_active:
            tier = request.user.subscription.tier

        tier = tier.upper()

        if tier in ('PRO', 'PREMIUM'):
            self.rate = '100/day'
        elif tier in ('PLUS', 'PAID'):
            self.rate = '10/day'
        else:
            self.rate = '3/day'

        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


class CommentCreateThrottle(UserRateThrottle):
    """
    Giới hạn comment của user trên word và post.
    Tất cả các tier: 20/day.
    """
    scope = 'comment_create'
    
    def get_rate(self):
        return '20/day'


class ReportThrottle(UserRateThrottle):
    """
    Giới hạn report trong ngày.
    Tất cả các tier: 10/day.
    """
    scope = 'report_create'
    
    def get_rate(self):
        return '10/day'
