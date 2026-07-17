import uuid
import logging
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import RewardItem, UserInventory, CoinWallet, CoinTransaction
from .coin_service import CoinService, InsufficientCoinsError

logger = logging.getLogger(__name__)

class ItemNotFoundError(Exception):
    """Vật phẩm không tồn tại hoặc không khả dụng để bán."""
    pass

class AlreadyOwnedError(Exception):
    """Người dùng đã sở hữu vật phẩm cosmetic này rồi."""
    pass

class InvalidPaymentMethodError(Exception):
    """Phương thức thanh toán không hợp lệ cho vật phẩm này."""
    pass


class ShopService:
    """
    Business logic layer cho các giao dịch trong Cửa Hàng.
    Đảm bảo row-level locking an toàn và ghi log transaction chi tiết.
    """

    @staticmethod
    @transaction.atomic
    def purchase_item(user, reward_item_id, lang: str, payment_method: str) -> tuple:
        """
        Thực hiện mua vật phẩm phần thưởng trong shop.
        
        Returns:
            tuple: (UserInventory_obj, list[CoinTransaction])
        """
        # 1. Query vật phẩm
        try:
            item = RewardItem.objects.get(id=reward_item_id, is_active=True, is_sellable=True)
        except (RewardItem.DoesNotExist, ValueError, TypeError):
            raise ItemNotFoundError("Vật phẩm không tồn tại hoặc không được bán trong Cửa Hàng.")

        # 2. Kiểm tra sở hữu đối với vật phẩm cosmetic (chỉ được sở hữu 1 lần)
        if item.reward_type in ['avatar_frame', 'title', 'badge', 'item']:
            if UserInventory.objects.filter(user=user, reward_item=item).exists():
                raise AlreadyOwnedError("Bạn đã sở hữu vật phẩm này từ trước.")

        # 3. Lock ví an toàn (Row-Level Locking)
        wallet = CoinService._get_wallet_for_update(user, lang)

        # Re-check ownership sau khi lock ví để tránh race condition
        if item.reward_type in ['avatar_frame', 'title', 'badge', 'item']:
            if UserInventory.objects.filter(user=user, reward_item=item).exists():
                raise AlreadyOwnedError("Bạn đã sở hữu vật phẩm này từ trước.")

        transactions = []
        group_id = uuid.uuid4()

        # 4. Kiểm tra logic giá và trừ tiền theo độ hiếm
        if item.rarity == 'common':
            # Tab 1: Utility Shop - Bắt buộc dùng free coin, hỗ trợ bù bằng paid
            if payment_method != 'free':
                raise InvalidPaymentMethodError("Vật phẩm phổ thông chỉ có thể mua bằng tiền Free.")
            
            price = item.price_free
            if wallet.free_balance >= price:
                wallet.free_balance -= price
                wallet.save(update_fields=['free_balance', 'updated_at'])
                
                txn = CoinTransaction.objects.create(
                    wallet=wallet, user=user,
                    transaction_type='SHOP_PURCHASE', balance_type='free',
                    amount=-price,
                    paid_balance_after=wallet.paid_balance,
                    free_balance_after=wallet.free_balance,
                    shop_balance_after=wallet.shop_balance,
                    reference_id=str(item.id),
                    note=f"Mua '{item.name}' bằng Free Coin"
                )
                transactions.append(txn)
            else:
                # Cơ chế Split Spend: trừ hết free, phần thiếu trừ vào paid
                deduct_free = wallet.free_balance
                deduct_paid = price - deduct_free
                
                if wallet.paid_balance < deduct_paid:
                    raise InsufficientCoinsError(
                        f"Không đủ coin để mua '{item.name}'. Cần {price} (Có: Free={deduct_free}, Paid={wallet.paid_balance})"
                    )
                
                wallet.free_balance = 0
                wallet.paid_balance -= deduct_paid
                wallet.save(update_fields=['free_balance', 'paid_balance', 'updated_at'])
                
                # Bản ghi log 1 (Free)
                txn_free = CoinTransaction.objects.create(
                    group_id=group_id,
                    wallet=wallet, user=user,
                    transaction_type='SHOP_PURCHASE', balance_type='free',
                    amount=-deduct_free,
                    paid_balance_after=wallet.paid_balance,
                    free_balance_after=wallet.free_balance,
                    shop_balance_after=wallet.shop_balance,
                    reference_id=str(item.id),
                    note=f"Mua '{item.name}' (Khấu trừ Free Coin - Split)"
                )
                # Bản ghi log 2 (Paid)
                txn_paid = CoinTransaction.objects.create(
                    group_id=group_id,
                    wallet=wallet, user=user,
                    transaction_type='SHOP_PURCHASE', balance_type='paid',
                    amount=-deduct_paid,
                    paid_balance_after=wallet.paid_balance,
                    free_balance_after=wallet.free_balance,
                    shop_balance_after=wallet.shop_balance,
                    reference_id=str(item.id),
                    note=f"Mua '{item.name}' (Bù trừ từ Paid Coin - Split)"
                )
                transactions.extend([txn_free, txn_paid])

        elif item.rarity in ['rare', 'epic']:
            # Tab 2: Elite Marketplace - Cơ chế Hybrid
            if payment_method not in ['free', 'paid', 'shop']:
                raise InvalidPaymentMethodError("Phương thức thanh toán không hợp lệ cho vật phẩm Tinh Anh.")
            
            if payment_method == 'free':
                price = item.price_free
                if wallet.free_balance >= price:
                    wallet.free_balance -= price
                    wallet.save(update_fields=['free_balance', 'updated_at'])
                    
                    txn = CoinTransaction.objects.create(
                        wallet=wallet, user=user,
                        transaction_type='SHOP_PURCHASE', balance_type='free',
                        amount=-price,
                        paid_balance_after=wallet.paid_balance,
                        free_balance_after=wallet.free_balance,
                        shop_balance_after=wallet.shop_balance,
                        reference_id=str(item.id),
                        note=f"Mua '{item.name}' bằng Free Coin (Tab Elite)"
                    )
                    transactions.append(txn)
                else:
                    # Bù bằng Paid
                    deduct_free = wallet.free_balance
                    deduct_paid = price - deduct_free
                    
                    if wallet.paid_balance < deduct_paid:
                        raise InsufficientCoinsError(
                            f"Không đủ coin để mua '{item.name}'. Cần {price} Free (Có: Free={deduct_free}, Paid={wallet.paid_balance})"
                        )
                    
                    wallet.free_balance = 0
                    wallet.paid_balance -= deduct_paid
                    wallet.save(update_fields=['free_balance', 'paid_balance', 'updated_at'])
                    
                    txn_free = CoinTransaction.objects.create(
                        group_id=group_id,
                        wallet=wallet, user=user,
                        transaction_type='SHOP_PURCHASE', balance_type='free',
                        amount=-deduct_free,
                        paid_balance_after=wallet.paid_balance,
                        free_balance_after=wallet.free_balance,
                        shop_balance_after=wallet.shop_balance,
                        reference_id=str(item.id),
                        note=f"Mua '{item.name}' (Khấu trừ Free Coin - Tab Elite)"
                    )
                    txn_paid = CoinTransaction.objects.create(
                        group_id=group_id,
                        wallet=wallet, user=user,
                        transaction_type='SHOP_PURCHASE', balance_type='paid',
                        amount=-deduct_paid,
                        paid_balance_after=wallet.paid_balance,
                        free_balance_after=wallet.free_balance,
                        shop_balance_after=wallet.shop_balance,
                        reference_id=str(item.id),
                        note=f"Mua '{item.name}' (Bù trừ từ Paid Coin - Tab Elite)"
                    )
                    transactions.extend([txn_free, txn_paid])
                    
            elif payment_method == 'paid':
                price = item.price_paid
                if wallet.paid_balance < price:
                    raise InsufficientCoinsError(f"Không đủ Paid Coin để mua '{item.name}' (Cần: {price}, Có: {wallet.paid_balance})")
                
                wallet.paid_balance -= price
                wallet.save(update_fields=['paid_balance', 'updated_at'])
                
                txn = CoinTransaction.objects.create(
                    wallet=wallet, user=user,
                    transaction_type='SHOP_PURCHASE', balance_type='paid',
                    amount=-price,
                    paid_balance_after=wallet.paid_balance,
                    free_balance_after=wallet.free_balance,
                    shop_balance_after=wallet.shop_balance,
                    reference_id=str(item.id),
                    note=f"Mua '{item.name}' bằng Paid Coin"
                )
                transactions.append(txn)
                
            elif payment_method == 'shop':
                price = item.price_shop
                if wallet.shop_balance < price:
                    raise InsufficientCoinsError(f"Không đủ Thần thạch/Đá quý để mua '{item.name}' (Cần: {price}, Có: {wallet.shop_balance})")
                
                wallet.shop_balance -= price
                wallet.save(update_fields=['shop_balance', 'updated_at'])
                
                txn = CoinTransaction.objects.create(
                    wallet=wallet, user=user,
                    transaction_type='SHOP_PURCHASE', balance_type='shop',
                    amount=-price,
                    paid_balance_after=wallet.paid_balance,
                    free_balance_after=wallet.free_balance,
                    shop_balance_after=wallet.shop_balance,
                    reference_id=str(item.id),
                    note=f"Mua '{item.name}' bằng Thần thạch/Đá quý"
                )
                transactions.append(txn)

        elif item.rarity == 'legendary':
            # Tab 3: Legendary Sanctuary - Chỉ bán bằng shop_balance (Thần thạch / Đá quý)
            if payment_method != 'shop':
                raise InvalidPaymentMethodError("Vật phẩm huyền thoại chỉ có thể mua bằng Thần thạch hoặc Đá quý.")
            
            price = item.price_shop
            if wallet.shop_balance < price:
                raise InsufficientCoinsError(f"Không đủ Thần thạch/Đá quý để mua '{item.name}' (Cần: {price}, Có: {wallet.shop_balance})")
            
            wallet.shop_balance -= price
            wallet.save(update_fields=['shop_balance', 'updated_at'])
            
            txn = CoinTransaction.objects.create(
                wallet=wallet, user=user,
                transaction_type='SHOP_PURCHASE', balance_type='shop',
                amount=-price,
                paid_balance_after=wallet.paid_balance,
                free_balance_after=wallet.free_balance,
                shop_balance_after=wallet.shop_balance,
                reference_id=str(item.id),
                note=f"Mua '{item.name}' bằng Thần thạch/Đá quý tại Điện Huyền Thoại"
            )
            transactions.append(txn)

        # 5. Cấp phát vật phẩm vào Inventory
        inv = UserInventory.objects.filter(user=user, reward_item=item).first()
        if inv:
            inv.quantity += 1
            inv.save(update_fields=['quantity'])
        else:
            inv = UserInventory.objects.create(
                user=user,
                reward_item=item,
                quantity=1,
                source_rule=None
            )

        # 6. Nếu là bonus_coins, nạp trực tiếp số coin đó vào ví Free của user (không qua giới hạn daily cày cuốc)
        if item.reward_type == 'bonus_coins' and item.coin_amount > 0:
            wallet.free_balance += item.coin_amount
            wallet.save(update_fields=['free_balance', 'updated_at'])
            
            CoinTransaction.objects.create(
                wallet=wallet, user=user,
                transaction_type='EARN_STUDY', balance_type='free',
                amount=item.coin_amount,
                paid_balance_after=wallet.paid_balance,
                free_balance_after=wallet.free_balance,
                shop_balance_after=wallet.shop_balance,
                reference_id=str(item.id),
                note=f"Nhận thưởng {item.coin_amount} Free Coin từ mua '{item.name}' trong Shop"
            )

        return inv, transactions
