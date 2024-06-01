class PaymentService:
    @staticmethod
    async def program_link() -> str:
        return "http://www.example.com"

    @staticmethod
    async def subscription_link() -> str:
        return "http://www.example.com"


payment_service = PaymentService()
